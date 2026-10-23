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
from combat.ext import void_touched_empty_palm as palm
from combat.ext.void_touched_cultivator import mark_count
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context, run_effects
from non_sphere_authority import NonSphereAuthorityService
from tests import worker2_support as W
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project

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


def _fight(tmp_path, service, project, *, name="fight", ac=1, saves=None, foe_kit=DAGGER, pools=None):
    """A real table fight: the acquired cultivator against one adjacent creature."""
    owner = bundle(service, project)
    overrides = dict(saves or {})

    def transform(bundles):
        for row in bundles:
            if row["actor_id"] != W.FOE:
                continue
            row["actor_template"]["armor_class"] = ac
            row["actor_template"]["saving_throws"] = {ability: overrides.get(ability, -50)
                                                      for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
            row["actor_template"]["maximum_hp"] = 400
            if pools is not None:
                for resource in row["actor_template"]["resources"]:
                    if resource["resource_id"] == "resource:core.qi":
                        resource["initial"] = pools
    return W.fixture(tmp_path / name, [], cl=CL, owner_bundle=owner,
                     foe_kit={"starting_kit": foe_kit} if foe_kit else None,
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
    assert any(event.event_type == "PASSIVE_TRIGGERED" and "has no Cultivation Points" in str((event.payload or {}).get("log"))
               for event in engine.events)


# ------------------------------------------------------------------------------------------------ Hollow the Weapon
@pytest.mark.parametrize("save,until", [(-50, "START_OF_TURN_AT"), (50, "END_OF_TURN_AT")])
def test_hollow_the_weapon_suppresses_treasure_weapon_properties_at_the_table(acquired, tmp_path, save, until):
    service, project = acquired
    treasure_kit = {"items": [], "resolved_treasure_weapon": {
        "chassis": {"item_id": "test.enchanted_jian", "name": "Enchanted Jian", "damage": "1d8 Slashing",
                    "properties": ""},
        "refinement_bonus": 0,
        "enchantments": [{"name": "Moonless-Yin Inscription",
                          "text": "Whenever you hit with the weapon, the target takes an additional 1d6 cold damage."}]}}
    combat, table, mid = _fight(tmp_path, service, project, name=f"hollow-enchanted-{save}",
                                saves={"CHA": save}, foe_kit=treasure_kit)
    before = W.reload(tmp_path / f"hollow-enchanted-{save}", mid)
    foe = before.state.actors[W.FOE]
    weapon = next(action for action in before.action_catalog.values()
                  if action.display_name == "Enchanted Jian attack" and action.owner_id == W.FOE)
    assert weapon.parameters["typed"]["mundane"] is False
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"], ITEM_PROMPT: [weapon.source_definition_id]})
    engine = W.reload(tmp_path / f"hollow-enchanted-{save}", mid)
    foe = engine.state.actors[W.FOE]
    hollowed = next(condition for condition in foe.conditions.values() if condition.condition_id == palm.HOLLOWED_ITEM)
    assert hollowed.expires_on.startswith(until)
    assert hollowed.data["disables_action"] == weapon.source_definition_id


def test_hollow_the_weapon_does_not_suppress_a_mundane_dagger(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = _fight(tmp_path, service, project, name="hollow-mundane", saves={"CHA": -50})
    cid = W.candidate(combat, mid, "Empty Palm: Hollow the Weapon", target=W.FOE).candidate_id
    W.settle(table, mid, cid, picks={DAMAGE_TYPE_PROMPT: ["FORCE"]})
    engine = W.reload(tmp_path / "hollow-mundane", mid)
    foe = engine.state.actors[W.FOE]
    from combat.weapon_delivery import available_weapons
    dagger = next(action for action in engine.action_catalog.values()
                  if action.display_name == "Bi Shou (Dagger) attack" and action.owner_id == W.FOE)
    assert "Bi Shou (Dagger) attack" in [action.display_name for action in available_weapons(engine, foe).values()]
    assert engine._action_candidates_impl(foe, dagger)
    assert not any(condition.condition_id == palm.HOLLOWED_ITEM for condition in foe.conditions.values())


def test_a_hollowed_shield_stops_earning_its_shield_bonus(monkeypatch):
    """The ``ac`` hook's own contract: it subtracts only while a hollowed Shield names that Shield."""
    from types import SimpleNamespace

    from combat import armour

    engine = SimpleNamespace()
    monkeypatch.setattr(armour, "shield_item_key", lambda _engine, _target: "item:shield")
    monkeypatch.setattr(armour, "shield_bonus_earning", lambda _engine, _target: 2)
    hollowed = SimpleNamespace(condition_id=palm.HOLLOWED_ITEM, data={"shield_item": "item:shield"})
    unrelated = SimpleNamespace(condition_id=palm.HOLLOWED_ITEM, data={"shield_item": "item:other"})
    target = SimpleNamespace(conditions={"a": hollowed}, entity_id="actor:x")
    assert palm.hollowed_shield(engine, target) is None
    target.conditions = {"a": unrelated}
    assert palm.hollowed_shield(engine, target) is None
    target.conditions = {}
    assert palm.hollowed_shield(engine, target) is None


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


def _unravel(tmp_path, service, project, *, cl, name, origin_save=None, check_roll=20, saves=None):
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
    # attack d20, 4d8 damage, (the effect's own resistance), the Cultivation Check
    _script(engine, [20, 4, 4, 4, 4, 20, check_roll])
    action = palm_action(engine, "Unravel Manifestation")
    run_effects(_context(engine, owner, action, foe), action.parameters["typed"]["effects"])
    return engine, owner, foe, qi


def test_unravel_suppresses_a_lower_source_cl_effect_until_the_next_turn(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, qi = _unravel(tmp_path, service, project, cl=CL - 2, name="unravel-lower")
    condition = _affected(engine)
    assert condition.condition_id == "condition:typed.suppressed.poisoned"  # suppressed, never removed
    rows = foe.turn_flags["typed_round_suppressed"]
    assert rows[-1]["boundary"] == "start" and rows[-1]["turn"] == owner.turns_started + 1
    assert owner.resources["resource:core.qi"] == qi  # the Action's cost is never refunded by the suppression
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
    assert check.payload["dc"] == 14 and check.payload["success"] is True
    assert _affected(engine).condition_id == "condition:typed.suppressed.poisoned"
    assert foe.turn_flags["typed_round_suppressed"][-1]["boundary"] == "start"


def test_unravel_equal_source_cl_fails_closed_when_the_check_fails(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL, name="unravel-equal-fail", check_roll=1)
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    assert not foe.turn_flags.get("typed_round_suppressed")


def test_unravel_higher_source_cl_gives_its_resistance_then_suppresses_to_the_turn_end(acquired, tmp_path):
    service, project = acquired
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL + 2, name="unravel-higher", check_roll=20)
    rows = foe.turn_flags["typed_round_suppressed"]
    assert rows[-1]["turn"] == owner.turns_started and rows[-1].get("boundary", "end") == "end"
    assert _affected(engine).condition_id == "condition:typed.suppressed.poisoned"
    ext.run("turn_end", engine, owner)
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    # A recorded resistance the effect wins keeps it active, with no Cultivation Check at all.
    engine, owner, foe, _ = _unravel(tmp_path, service, project, cl=CL + 2, name="unravel-resist",
                                     origin_save={"ability": "CON", "dc": 5}, check_roll=20, saves={"CON": 50})
    assert _affected(engine).condition_id == "condition:typed.poisoned"
    assert not any(event.event_type == "CHECK_ROLLED" and (event.payload or {}).get("skill") == "Cultivation Check"
                   for event in engine.events)


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
