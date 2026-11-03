"""MGR-T14: Empty Palm (CL6, tianxia.subpath.qi.void_touched_cultivator) as one whole record.

Every ownership fact comes from a recorded native acquisition (NS1R evidence and the
Subpath selection compiled through combat/authority_projection.py); no test injects a
feature id, a Scar, a hit or a mark into a fight.

The record is exercised where each printed clause can fail: the three offered
operations, the real melee attack against the real defense, the cost and the shared
Void Mark across a table commit and a cold replay, the Force-or-Void question, the
Constitution and Charisma saves with their real DCs, the pool drain and the no-regain
gate, the extra Force damage for a creature with no Cultivation Points, an item's
properties suppressed while the item stays, Unravel Manifestation against a lower,
equal and higher Source CL (including its own resistance and the Cultivation Check),
and the default-inert guards for a character that does not own the feature.
"""
import pytest

from app.core import Database, Settings
from combat import ext
from combat.authority_projection import compile_project_character, project_sheet
from combat.canonical import canonical_sha256
from combat.ext import void_touched_empty_palm as palm
from combat.ext.void_touched_cultivator import mark_count
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context, run_effects
from non_sphere_authority import NonSphereAuthorityService
from tests import worker2_support as W
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.void_family_support import insert_project

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
EMPTY_PALM = PARENT + ".feature.empty_palm"
SCAR = "My reflection no longer appears."
VOID_SPHERE = "tianxia.sphere.void"
CL = 6
DAGGER = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}
DAGGER_ACTION = "action:typed.bab13d9948.weapon.bi_shou"
DAMAGE_TYPE_PROMPT = "choice:needle.empty_palm_damage_type"
POOL_PROMPT = "choice:needle.empty_palm_pool"
ITEM_PROMPT = "choice:needle.empty_palm_item"
PROPERTY_PROMPT = "choice:needle.empty_palm_property"


# ------------------------------------------------------------------------------------------------ acquisition
def _build_acquisition(root, cl=CL):
    """A real NS1R project with the Secret Law acquired and its permanent Scar recorded."""
    settings = Settings.from_env(ROOT, root / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = f"empty-palm-native-{cl}"
    insert_project(db, project, cl)
    service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: cl - 1},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", cl, cl - 1),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    service.select_subpath(project, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[VOID_SPHERE])
    service.set_resource(project, QI, current=30, maximum=30)
    return service, project


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    return _build_acquisition(tmp_path_factory.mktemp("empty-palm-acquisition"))


def owner_sheet(service, project, *, cl=CL, spheres=(VOID_SPHERE,), name="Void cultivator"):
    state = service.get_state(project)
    doc = sheet([], cl=cl, name=name)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = list(spheres)
    doc["path_and_subpath"] = {"paths": state["paths"]}
    return doc


def bundle(service, project, actor_id=W.OWNER, *, cl=CL):
    return compile_project_character(service, project, owner_sheet(service, project, cl=cl),
                                     actor_id=actor_id, reaction_plan={"ask": True})


def palm_action(engine, option):
    for action in engine.action_catalog.values():
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        if typed.get("source") == EMPTY_PALM and typed.get("option_label") == option:
            return action
    raise AssertionError(f"no compiled Empty Palm option {option!r}")


def _fight(tmp_path, service, project, *, name="fight", ac=1, saves=None, foe_kit=DAGGER, pools=None, item_setup=False, accurate_foe=False):
    """A real table fight: the acquired cultivator against one adjacent creature."""
    owner = bundle(service, project)
    overrides = dict(saves or {})

    def transform(bundles):
        for row in bundles:
            if row["actor_id"] != W.FOE:
                continue
            if accurate_foe:
                for action in row["action_catalog"]:
                    typed = action.get("parameters", {}).get("typed", {})
                    if typed.get("weapon"):
                        typed["numbers"]["attack_bonus"] = 100
            row["actor_template"]["armor_class"] = ac
            row["actor_template"]["saving_throws"] = {ability: overrides.get(ability, -50)
                                                      for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
            row["actor_template"]["maximum_hp"] = 400
            if item_setup:
                aid = "action:test.raise_jade_ward"
                row["actor_template"]["action_ids"].append(aid)
                row["action_catalog"].append({
                    "source_definition_id": aid, "display_name": "Raise jade ward", "owner_id": W.FOE,
                    "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
                    "parameters": {"typed": {"source": aid, "numbers": {}, "duration": {"kind": "instant"},
                        "effects": [{"type": "test_palm_item_benefit", "item_key": "test.implement.jade_focus"}]}}})
            if pools is not None:
                for resource in row["actor_template"]["resources"]:
                    if resource["resource_id"] == "resource:core.qi":
                        resource["initial"] = pools
            row.pop("bundle_sha256", None)
            row["bundle_sha256"] = canonical_sha256(row)
    foe_doc = sheet([], cl=CL, kit={"starting_kit": foe_kit} if foe_kit else None)
    # These item-property tests need a bearer entitled to the physical shield bonus.
    foe_doc["proficiencies"] = {"armor": ["shields"]}
    return W.fixture(tmp_path / name, [], cl=CL, owner_bundle=owner,
                     foe_sheet=foe_doc,
                     positions={W.OWNER: {"x": 3, "y": 6}, W.ALLY: {"x": 12, "y": 12}, W.FOE: {"x": 4, "y": 6}},
                     bundle_transform=transform, seed="EMPTY-PALM-" + name)


def _context(engine, actor, action, target):
    return Context(engine, actor, action, None, dict(action.parameters["typed"]), [target], target)


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


# ------------------------------------------------------------------------------------------------ what is offered
def test_native_acquisition_compiles_all_three_operations(acquired):
    service, project = acquired
    projected = project_sheet(service, project, owner_sheet(service, project))
    assert projected["path_and_subpath"]["acquisition_choices"][PARENT] == {"void_scar": SCAR}
    rows = [(action.get("parameters", {}).get("typed") or {})
            for action in bundle(service, project)["action_catalog"]]
    typed = [row for row in rows if row.get("source") == EMPTY_PALM]
    assert [row["option_label"] for row in typed] == ["Unravel Manifestation", "Empty the Meridian",
                                                      "Hollow the Weapon"]
    for row in typed:
        assert row["void_scar"] == SCAR and row["min_cl"] == CL
        assert row["numbers"]["source_cl"] == CL
        attack = row["effects"][0]
        assert attack["type"] == "attack" and attack["attack_kind"] == "cultivation_melee"
        damage = next(item for item in attack["on_hit"] if item["type"] == "damage")
        assert damage["dice"] == {"count": 4, "sides": 8} and damage["formula"] == "key_ability_modifier"
        assert damage["damage_types"] == ["force", "void"]
        assert any(item["type"] == "mark" and item["mark"] == "Void Mark" for item in attack["on_hit"])
    meridian = next(row for row in typed if row["option_label"] == "Empty the Meridian")
    save = next(item for item in meridian["effects"][0]["on_hit"] if item["type"] == "save")
    assert save["ability"] == "con"
    assert [item["operation"] for item in save["on_fail"]] == ["meridian"]
    assert [item["operation"] for item in save["on_success"]] == ["meridian"]
    hollow = next(row for row in typed if row["option_label"] == "Hollow the Weapon")
    assert next(item for item in hollow["effects"][0]["on_hit"] if item["type"] == "save")["ability"] == "cha"


def test_the_table_offers_all_three_operations_and_no_other_character_gets_them(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="offer")
    engine = W.reload(tmp_path / "offer", mid)
    names = {engine.action_catalog[c.source_definition_id].display_name
             for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog}
    assert {"Empty Palm: Unravel Manifestation", "Empty Palm: Empty the Meridian",
            "Empty Palm: Hollow the Weapon"} <= names
    for option in ("Unravel Manifestation", "Empty the Meridian", "Hollow the Weapon"):
        action = palm_action(engine, option)
        assert action.economy == EconomyKind.ACTION and action.range_ft == 5
        assert list(action.costs) == [("resource:core.qi", 3)]
    for actor_id in (W.ALLY, W.FOE):
        assert not [key for key in engine.state.actors[actor_id].action_ids
                    if (engine.action_catalog.get(key) is not None
                        and ((engine.action_catalog[key].parameters or {}).get("typed") or {}).get("source") == EMPTY_PALM)]


# ------------------------------------------------------------------------------------------------ hit, cost, mark
def test_hit_deals_force_or_void_damage_marks_and_spends_three_qi_then_reloads(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="hit")
    before = W.reload(tmp_path / "hit", mid)
    assert before.state.actors[W.OWNER].resources["resource:core.qi"] == 30
    victim = before.state.actors[W.FOE]
    assert mark_count(victim, W.OWNER) == 0
    hp = victim.current_hp
    cid = W.candidate(combat, mid, "Empty Palm: Empty the Meridian", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["VOID"], POOL_PROMPT: ["resource:core.qi"]})
    damage_prompt = next(prompt for prompt in prompts if prompt["context"]["reaction_source_id"] == DAMAGE_TYPE_PROMPT)
    assert [option["label"] for option in damage_prompt["choice"]["options"]] == ["Force damage", "Void damage"]
    assert damage_prompt["context"]["reactor_id"] == W.OWNER
    engine = W.reload(tmp_path / "hit", mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert owner.resources["resource:core.qi"] == 27
    committed = [event.payload for event in engine.events
                 if event.event_type == "DAMAGE_COMMITTED" and W.FOE in event.target_ids]
    assert len(committed) == 1 and committed[0]["damage_type"] == "VOID"
    assert committed[0]["hp_damage"] == hp - foe.current_hp and 4 <= committed[0]["hp_damage"] <= 34
    assert mark_count(foe, W.OWNER) == 1
    mark = next(condition for condition in foe.conditions.values()
                if condition.condition_id.startswith("condition:typed.mark.void_mark."))
    assert mark.data["count"] == 1 and mark.data["ends_with_scene"] == 1


def test_miss_spends_the_cost_and_deals_neither_damage_nor_a_mark(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, ac=90, name="miss")
    before = W.reload(tmp_path / "miss", mid).state.actors[W.FOE].current_hp
    cid = W.candidate(combat, mid, "Empty Palm: Empty the Meridian", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={})
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [DAMAGE_TYPE_PROMPT]
    engine = W.reload(tmp_path / "miss", mid)
    foe, owner = engine.state.actors[W.FOE], engine.state.actors[W.OWNER]
    assert owner.resources["resource:core.qi"] == 27  # the printed cost is still spent
    assert foe.current_hp == before
    assert mark_count(foe, W.OWNER) == 0
    assert not any(condition.condition_id.startswith("condition:typed.mark.")
                   for condition in foe.conditions.values())


# ------------------------------------------------------------------------------------------------ Empty the Meridian
def test_empty_the_meridian_failed_save_drains_the_chosen_pool_and_blocks_regain(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="meridian-fail", saves={"CON": -50})
    before = W.reload(tmp_path / "meridian-fail", mid).state.actors[W.FOE].resources["resource:core.qi"]
    cid = W.candidate(combat, mid, "Empty Palm: Empty the Meridian", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"], POOL_PROMPT: ["resource:core.qi"]})
    pool_prompt = next(prompt for prompt in prompts if prompt["context"]["reaction_source_id"] == POOL_PROMPT)
    assert [option["id"] for option in pool_prompt["choice"]["options"]] == ["resource:core.qi"]
    engine = W.reload(tmp_path / "meridian-fail", mid)
    foe = engine.state.actors[W.FOE]
    assert foe.resources["resource:core.qi"] == before - 4  # Proficiency Bonus 4
    gate = next(condition for condition in foe.conditions.values() if condition.condition_id == palm.NO_REGAIN)
    assert gate.expires_on == f"START_OF_TURN_AT:{W.FOE}:{foe.turns_started + 1}"
    held = foe.resources["resource:core.qi"]
    engine._gain_resource(foe, "resource:core.qi", 5, "action:test.regain")
    assert foe.resources["resource:core.qi"] == held
    assert any(event.event_type == "GM_RIDER" and "cannot regain" in str((event.payload or {}).get("rider"))
               for event in engine.events)
    _turn(engine, W.FOE)  # the start of the target's next turn
    assert not any(condition.condition_id == palm.NO_REGAIN for condition in foe.conditions.values())
    engine._gain_resource(foe, "resource:core.qi", 5, "action:test.regain")
    assert foe.resources["resource:core.qi"] > held  # the gate is gone, the pool can be regained again


def test_empty_the_meridian_successful_save_loses_one_point_and_no_gate(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="meridian-win", saves={"CON": 50})
    before = W.reload(tmp_path / "meridian-win", mid).state.actors[W.FOE].resources["resource:core.qi"]
    cid = W.candidate(combat, mid, "Empty Palm: Empty the Meridian", target=W.FOE).candidate_id
    W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"], POOL_PROMPT: ["resource:core.qi"]})
    engine = W.reload(tmp_path / "meridian-win", mid)
    foe = engine.state.actors[W.FOE]
    assert foe.resources["resource:core.qi"] == before - 1
    assert not any(condition.condition_id == palm.NO_REGAIN for condition in foe.conditions.values())


def test_a_creature_with_no_cultivation_points_takes_double_proficiency_force(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="no-points", pools=0)
    cid = W.candidate(combat, mid, "Empty Palm: Empty the Meridian", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["VOID"]})
    assert POOL_PROMPT not in [prompt["context"]["reaction_source_id"] for prompt in prompts]
    engine = W.reload(tmp_path / "no-points", mid)
    packets = [event.payload for event in engine.events
               if event.event_type == "DAMAGE_COMMITTED" and W.FOE in event.target_ids]
    assert [packet["damage_type"] for packet in packets] == ["VOID", "FORCE"]
    assert packets[1]["hp_damage"] == 8  # 2 x Proficiency Bonus 4, beside the hit's damage
    gate = next(condition for condition in engine.state.actors[W.FOE].conditions.values()
                if condition.condition_id == palm.NO_REGAIN)  # the failed save still blocks regain
    assert gate.expires_on == f"START_OF_TURN_AT:{W.FOE}:{engine.state.actors[W.FOE].turns_started + 1}"
    assert any(event.event_type == "PASSIVE_TRIGGERED" and "has no Cultivation Points" in str((event.payload or {}).get("log"))
               for event in engine.events)


# ------------------------------------------------------------------------------------------------ Hollow the Weapon
FLAME_PROPERTY = "tianxia.treasure.enchantment.flame_vein_inscription"
FROST_PROPERTY = "tianxia.treasure.enchantment.frost_meridian_inscription"


def _cultivated_kit(property_ids=(FLAME_PROPERTY, FROST_PROPERTY), *, properties=""):
    import json

    authority = json.loads((ROOT / "authority/Tianxia_Treasure_Weapon_Authority_R1.json").read_text())
    inscriptions = [row for row in authority["enchantments"] if row["enchantment_id"] in property_ids]
    assert len(inscriptions) == len(property_ids)
    return {"items": [], "resolved_treasure_weapon": {
        "name": "Inscribed dagger",
        "chassis": {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Dagger",
                    "damage": "1d4 Piercing", "properties": properties},
        "refinement_bonus": 2, "enchantments": inscriptions}}

def _item_key(key):
    return f"{W.FOE}|{key}"


@pytest.mark.parametrize("save", [-50, 50])
@pytest.mark.parametrize("shield", [False, True])
def test_hollow_keeps_mundane_attacks_and_physical_shield_protection(acquired, tmp_path, save, shield):
    from combat import armour, carry
    from combat.weapon_delivery import available_weapons

    service, project = acquired
    kit = {"items": [*DAGGER["items"], *([{"item_id": "tianxia.mortal.armor.shield",
                                        "name": "Shield", "quantity": 1}] if shield else [])]}
    name = f"mundane-{save}-{shield}"
    combat, table, mid = _fight(tmp_path, service, project, name=name, saves={"CHA": save}, foe_kit=kit)
    engine = W.reload(tmp_path / name, mid)
    before = armour.shield_bonus_earning(engine, engine.state.actors[W.FOE])
    ac_before = engine._ac_modifier(engine.state.actors[W.FOE])
    key = armour.shield_item_key(engine, engine.state.actors[W.FOE]) if shield else "tianxia.mortal.weapon.bi_shou"
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"], ITEM_PROMPT: [_item_key(key)]})
    assert PROPERTY_PROMPT not in [p["context"]["reaction_source_id"] for p in prompts]
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    assert not any(c.condition_id == palm.HOLLOWED_ITEM for c in foe.conditions.values())
    assert "Bi Shou (Dagger) attack" in [a.display_name for a in available_weapons(engine, foe).values()]
    assert armour.shield_bonus_earning(engine, foe) == before
    assert engine._ac_modifier(foe) == ac_before
    assert before == (2 if shield else 0)
    assert carry.holds(engine, foe, key)
    W.turn(table, mid, W.FOE)
    assert W.candidate(combat, mid, "Bi Shou (Dagger) attack", target=W.OWNER)


@pytest.mark.parametrize("save", [-50, 50])
def test_hollow_selects_actual_named_properties_and_restores_them(acquired, tmp_path, monkeypatch, save):
    from combat import carry
    from combat.ext import item_cultivation as items

    service, project = acquired
    seats = {}
    real_ask = palm._ask

    def recording_ask(ctx, chooser, name, options, **kwargs):
        seats[name] = chooser.entity_id
        return real_ask(ctx, chooser, name, options, **kwargs)

    monkeypatch.setattr(palm, "_ask", recording_ask)
    name = f"cultivated-{save}"
    combat, table, mid = _fight(tmp_path, service, project, name=name, saves={"CHA": save},
                                foe_kit=_cultivated_kit(), accurate_foe=True)
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"],
                                             ITEM_PROMPT: [_item_key("treasure_weapon")],
                                             PROPERTY_PROMPT: [FLAME_PROPERTY]})
    assert seats["empty_palm_item"] == W.OWNER
    engine = W.reload(tmp_path / name, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    receipts = [c for c in foe.conditions.values() if c.condition_id == palm.HOLLOWED_ITEM]
    wanted = {"refinement", FLAME_PROPERTY, FROST_PROPERTY} if save < 0 else {FLAME_PROPERTY}
    assert {c.data["property_id"] for c in receipts} == wanted
    expiry = (f"START_OF_TURN_AT:{W.OWNER}:{owner.turns_started + 1}" if save < 0
              else f"END_OF_TURN_AT:{W.OWNER}:{owner.turns_started}")
    assert all(c.expires_on == expiry for c in receipts)
    assert carry.holds(engine, foe, "treasure_weapon")
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == W.FOE and a.display_name == "Inscribed dagger attack")
    context = _context(engine, foe, action, owner)
    assert items.refinement_attack(context, foe) == (-2 if save < 0 else None)
    assert items.refinement_damage(context, owner, {}) == (-2 if save < 0 else None)
    rows = {row["item_property"]: row for row in action.parameters["typed"]["effects"][0]["on_hit"]
            if row.get("item_property")}
    assert set(rows) == {FLAME_PROPERTY, FROST_PROPERTY}
    assert items.property_effect_allowed(context, rows[FLAME_PROPERTY]) is False
    assert items.property_effect_allowed(context, rows[FROST_PROPERTY]) == (False if save < 0 else None)
    if save > 0:
        assert seats["empty_palm_property"] == W.OWNER
        prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == PROPERTY_PROMPT)
        assert {o["id"] for o in prompt["choice"]["options"]} == {
            "refinement", FLAME_PROPERTY, FROST_PROPERTY}
    W.turn(table, mid, W.FOE)
    if save < 0:
        W.settle(table, mid, W.candidate(combat, mid, "Inscribed dagger attack", target=W.OWNER).candidate_id)
        engine = W.reload(tmp_path / name, mid)
        packets = [e.payload for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == W.FOE]
        assert packets and {p["damage_type"] for p in packets} == {"PIERCING"}
    else:
        engine = W.reload(tmp_path / name, mid)
        assert not any(c.condition_id == palm.HOLLOWED_ITEM for c in engine.state.actors[W.FOE].conditions.values())
    W.turn(table, mid, W.OWNER)
    engine = W.reload(tmp_path / name, mid)
    assert not any(c.condition_id == palm.HOLLOWED_ITEM for c in engine.state.actors[W.FOE].conditions.values())


def test_hollow_suppresses_returning_inscription_without_preventing_the_throw(acquired, tmp_path):
    from combat import carry

    service, project = acquired
    returning = "tianxia.treasure.enchantment.returning_inscription"
    name = "hollow-returning"
    combat, table, mid = _fight(
        tmp_path, service, project, name=name, saves={"CHA": -50},
        foe_kit=_cultivated_kit((returning,), properties="Thrown 20/60"), accurate_foe=True)
    W.settle(table, mid, W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id,
             picks={DAMAGE_TYPE_PROMPT: ["FORCE"]})
    W.turn(table, mid, W.FOE)
    W.settle(table, mid, W.candidate(combat, mid, "Inscribed dagger thrown", target=W.OWNER).candidate_id)
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    assert not carry.holds(engine, foe, "treasure_weapon")
    dropped = next(c for c in foe.conditions.values()
                   if c.condition_id == carry.DROPPED and c.data.get("item_key") == "treasure_weapon")
    assert dropped.data["dropped_at"] == engine.state.actors[W.OWNER].position.model_dump(mode="json")
    assert any(c.condition_id == palm.HOLLOWED_ITEM and c.data.get("property_id") == returning
               for c in foe.conditions.values())


@pytest.mark.parametrize("save", [-50, 50])
def test_hollow_suppresses_shield_cultivation_not_physical_protection(acquired, tmp_path, save):
    import json

    from combat import armour
    from combat.ext import item_cultivation, treasure_armor

    authority = json.loads((ROOT / "authority/Tianxia_Treasure_Armor_Authority_R1.json").read_text())
    shield = next(row for row in authority["chassis"] if row["armor_category"] == "shield")
    enhancement = next(row for row in authority["enhancements"]
                       if row["enhancement_id"].endswith(".fire_shedding_lining"))
    fid = enhancement["enhancement_id"]
    kit = {"items": [], "resolved_treasure_armor": {
        "name": "Ward shield", "chassis": shield, "enhancements": [enhancement],
        "refinement_bonus": 2}}
    service, project = acquired
    name = f"ward-shield-{save}"
    combat, table, mid = _fight(tmp_path, service, project, name=name, saves={"CHA": save}, foe_kit=kit)
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    assert [row["feature_id"] for row in treasure_armor.rows(engine, foe)] == [fid]
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"],
                                    ITEM_PROMPT: [_item_key("treasure_armor")], PROPERTY_PROMPT: [fid]})
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    assert not treasure_armor.rows(engine, foe)
    assert armour.shield_bonus_earning(engine, foe) == 2
    assert item_cultivation.refinement_ac(engine, foe) == (-2 if save < 0 else None)
    wanted = {"refinement", fid} if save < 0 else {fid}
    assert {c.data["property_id"] for c in foe.conditions.values() if c.condition_id == palm.HOLLOWED_ITEM} == wanted


def test_hollow_restores_weight_suppressed_by_a_shield_property(acquired, tmp_path):
    import json

    from combat import carry

    authority = json.loads((ROOT / "authority/Tianxia_Treasure_Armor_Authority_R1.json").read_text())
    shield = next(row for row in authority["chassis"] if row["armor_category"] == "shield")
    lightening = next(row for row in authority["enhancements"]
                      if row["enhancement_id"].endswith(".weightless_harness"))
    service, project = acquired
    name = "hollow-weightless-shield"
    kit = {"items": [], "resolved_treasure_armor": {
        "name": "Lightened shield", "chassis": shield, "enhancements": [lightening], "refinement_bonus": 0}}
    combat, table, mid = _fight(tmp_path, service, project, name=name, saves={"CHA": -50}, foe_kit=kit)
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    before = carry.weight(engine, foe)
    item = carry.item_of(carry.carrying_of(engine, W.FOE), key="treasure_armor")
    extra_weight = float(item["weight_lb"])
    assert extra_weight > 0
    W.settle(table, mid, W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id,
             picks={DAMAGE_TYPE_PROMPT: ["FORCE"]})
    engine = W.reload(tmp_path / name, mid)
    assert carry.weight(engine, engine.state.actors[W.FOE]) == before + extra_weight
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"])
    W.turn(table, mid, W.OWNER)
    engine = W.reload(tmp_path / name, mid)
    assert carry.weight(engine, engine.state.actors[W.FOE]) == before


@ext.effect("test_palm_item_benefit")
def _item_benefit(ctx, row):
    """Synthetic active implement property, installed by an ordinary table action."""
    ctx.engine._apply_condition(ctx.actor, "condition:typed.state.test_item_ward", ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"item_key": row["item_key"], "name": "Jade ward (+3 AC)"})
    run_effects(ctx, [{"type": "ac_bonus", "flat": 3, "applies_to": "self", "expires_on": "UNTIL_REMOVED"}])


def test_hollow_discovers_and_suppresses_nonweapon_implement_property(acquired, tmp_path):
    from combat import carry

    service, project = acquired
    name = "hollow-focus"
    focus = "test.implement.jade_focus"
    combat, table, mid = _fight(tmp_path, service, project, name=name, item_setup=True,
                                foe_kit={"items": [{"item_id": focus, "name": "Jade focus", "quantity": 1}]})
    W.turn(table, mid, W.FOE)
    W.settle(table, mid, W.candidate(combat, mid, "Raise jade ward").candidate_id)
    W.turn(table, mid, W.OWNER)
    engine = W.reload(tmp_path / name, mid)
    assert any(m.target_field == "armor_class" and m.value == 3 for m in engine.state.actors[W.FOE].modifiers.values())
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    prompts = W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"], ITEM_PROMPT: [_item_key(focus)]})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == ITEM_PROMPT)
    assert [(o["id"], o["label"]) for o in prompt["choice"]["options"]] == [(_item_key(focus), "Jade focus")]
    engine = W.reload(tmp_path / name, mid)
    foe = engine.state.actors[W.FOE]
    assert carry.holds(engine, foe, focus)
    assert any(c.condition_id == "condition:typed.suppressed.state.test_item_ward" for c in foe.conditions.values())
    assert any(m.target_field == "suppressed:armor_class" and m.value == 3 for m in foe.modifiers.values())
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"])
    W.turn(table, mid, W.OWNER)
    engine = W.reload(tmp_path / name, mid)
    assert any(m.target_field == "armor_class" and m.value == 3 for m in engine.state.actors[W.FOE].modifiers.values())


# ------------------------------------------------------------------------------------------------ Unravel Manifestation
def _hex(engine, cl):
    """A real compiled action standing in for an opponent's technique at a chosen Cultivation Level."""
    action = ActionDefinition(source_definition_id=f"action:test.hex{cl}", display_name="Test Hex",
                              owner_id=W.FOE, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=30,
                              parameters={"typed": {"source": "TAL_VOID_VOID_MERIDIAN_SEAL",
                                                    "numbers": {"cl": cl, "save_dc": 14}}})
    engine.action_catalog[action.source_definition_id] = action
    return action


def _affected(engine):
    return next(condition for condition in engine.state.actors[W.FOE].conditions.values()
                if "poisoned" in condition.condition_id)


def _unravel(tmp_path, service, project, *, cl, name, origin_save=None, check_roll=20, saves=None,
             resistance_roll=20):
    """One real hit + Unravel against a creature bearing exactly one effect from a technique of ``cl``."""
    combat, table, mid = _fight(tmp_path, service, project, name=name, saves=saves)
    engine = W.reload(tmp_path / name, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    technique = _hex(engine, cl)
    data = {"label": "Test poison"}
    if origin_save:
        data["origin_save"] = origin_save
    engine._apply_condition(foe, "condition:typed.poisoned", technique.source_definition_id,
                            technique.owner_id, expires_on="UNTIL_REMOVED", data=data)
    qi = owner.resources["resource:core.qi"]
    from tests.test_auto_lane4 import _script
    # A noncritical hit consumes exactly four d8s. Only a higher-CL effect
    # with a recorded resistance rolls that save; a successful save skips the check.
    dice = [15, 4, 4, 4, 4]
    if cl > CL and origin_save:
        dice.append(resistance_roll)
    if cl >= CL and check_roll is not None:
        dice.append(check_roll)
    remaining = _script(engine, dice)
    action = palm_action(engine, "Unravel Manifestation")
    run_effects(_context(engine, owner, action, foe), action.parameters["typed"]["effects"])
    assert not remaining, f"Unconsumed scripted dice: {remaining}"
    return engine, owner, foe, qi


def test_unravel_suppresses_a_lower_source_cl_effect_until_the_next_turn(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, qi = _unravel(tmp_path, service, project, cl=CL - 2, name="unravel-lower")
    condition = _affected(engine)
    assert condition.condition_id == "condition:typed.suppressed.poisoned"  # suppressed, never removed
    rows = foe.turn_flags["typed_round_suppressed"]
    assert rows[-1]["boundary"] == "start" and rows[-1]["turn"] == owner.turns_started + 1
    assert owner.resources["resource:core.qi"] == qi  # the suppression itself spends and refunds nothing (run_effects pays no Action cost)
    assert mark_count(foe, W.OWNER) == 1  # the hit still marked it
    assert not any(event.event_type == "CHECK_ROLLED" and (event.payload or {}).get("skill") == "Cultivation Check"
                   for event in engine.events)  # a lower Source CL needs no check
    _turn(engine, W.OWNER)
    assert _affected(engine).condition_id == "condition:typed.poisoned"


def test_unravel_equal_source_cl_needs_the_cultivation_check(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL, name="unravel-equal", check_roll=20)
    check = next(event for event in engine.events
                 if event.event_type == "CHECK_ROLLED" and (event.payload or {}).get("skill") == "Cultivation Check")
    assert check.payload["actor"]["dice"] == [20]
    assert check.payload["dc"] == 14 and check.payload["success"] is True
    assert _affected(engine).condition_id == "condition:typed.suppressed.poisoned"
    assert foe.turn_flags["typed_round_suppressed"][-1]["boundary"] == "start"


def test_unravel_equal_source_cl_fails_closed_when_the_check_fails(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL, name="unravel-equal-fail", check_roll=1)
    check = next(event for event in engine.events
                 if event.event_type == "CHECK_ROLLED" and event.payload.get("skill") == "Cultivation Check")
    assert check.payload["actor"]["dice"] == [1]
    assert check.payload["actor"]["total"] < check.payload["dc"] == 14
    assert check.payload["success"] is False
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    assert not foe.turn_flags.get("typed_round_suppressed")


def test_unravel_higher_source_cl_gives_its_resistance_then_suppresses_to_the_turn_end(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL + 2, name="unravel-higher", check_roll=20)
    check = next(event for event in engine.events
                 if event.event_type == "CHECK_ROLLED" and event.payload.get("skill") == "Cultivation Check")
    assert check.payload["actor"]["dice"] == [20] and check.payload["success"] is True
    rows = foe.turn_flags["typed_round_suppressed"]
    assert rows[-1]["turn"] == owner.turns_started and rows[-1].get("boundary", "end") == "end"
    assert _affected(engine).condition_id == "condition:typed.suppressed.poisoned"
    ext.run("turn_end", engine, owner)
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    # A recorded resistance the effect wins keeps it active, with no Cultivation Check at all.
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL + 2, name="unravel-resist",
                                     origin_save={"ability": "CON", "dc": 5}, check_roll=None, saves={"CON": 50})
    resistance = next(event for event in engine.events if event.event_type == "SAVE_ROLLED")
    assert resistance.payload["dice"] == [20] and resistance.payload["success"] is True
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    assert not any(event.event_type == "CHECK_ROLLED" and (event.payload or {}).get("skill") == "Cultivation Check"
                   for event in engine.events)


@pytest.mark.parametrize("check_roll,success", [(20, True), (1, False)])
def test_unravel_higher_cl_after_failed_resistance_uses_the_scripted_check(acquired, tmp_path, check_roll, success):
    service, project = acquired
    engine, _, _, _ = _unravel(
        tmp_path, service, project, cl=CL + 2, name=f"unravel-resistance-failed-{check_roll}",
        origin_save={"ability": "CON", "dc": 14}, resistance_roll=1, check_roll=check_roll)
    resistance = next(event for event in engine.events if event.event_type == "SAVE_ROLLED")
    assert resistance.payload["dice"] == [1] and resistance.payload["success"] is False
    check = next(event for event in engine.events
                 if event.event_type == "CHECK_ROLLED" and event.payload.get("skill") == "Cultivation Check")
    assert check.payload["actor"]["dice"] == [check_roll]
    assert check.payload["success"] is success
    assert ("suppressed" in _affected(engine).condition_id) is success


def test_unravel_does_not_offer_bookkeeping_rows_and_is_default_inert(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="unravel-inert")
    engine = W.reload(tmp_path / "unravel-inert", mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    technique = _hex(engine, CL - 2)
    engine._apply_condition(foe, "condition:typed.poisoned", technique.source_definition_id,
                            technique.owner_id, expires_on="UNTIL_REMOVED", data={"label": "Test poison"})
    entries = [(kind, key) for kind, key, _ in palm.effects_on(engine, foe)]
    assert [key for _, key in entries] == [next(key for key, condition in foe.conditions.items()
                                                if condition.condition_id == "condition:typed.poisoned")]
    assert not [key for _, key in entries
                if foe.conditions[key].condition_id.startswith(("condition:typed.mark.", "condition:typed.suppressed.",
                                                                "condition:typed.equipment_grip"))]
    plain = engine.action_catalog["action:test.hex4"]
    before = engine.state.model_dump(mode="json")
    ctx = Context(engine, engine.state.actors[W.ALLY], plain, None, {}, [foe], foe)
    palm.palm_operation(ctx, {"operation": "unravel", "applies_to": "target"})
    palm.palm_operation(ctx, {"operation": "meridian", "applies_to": "target"})
    palm.palm_operation(ctx, {"operation": "hollow", "applies_to": "target"})
    assert engine.state.model_dump(mode="json") == before


def test_the_force_or_void_question_is_asked_of_a_player_seat_only(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="seats")
    engine = W.reload(tmp_path / "seats", mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    ctx = _context(engine, owner, palm_action(engine, "Empty the Meridian"), foe)
    engine.typed_control_modes[W.OWNER] = "LOCAL_AUTO"
    assert palm.force_or_void(ctx, ["FORCE", "VOID"], [foe]) is None  # a computer decides for itself
    engine.typed_control_modes[W.OWNER] = "MANUAL"
    assert palm.force_or_void(ctx, ["FORCE"], [foe]) is None  # one printed type is not a choice
