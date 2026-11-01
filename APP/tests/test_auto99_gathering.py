"""Harvesting stays GM-managed until source, choice and lifecycle producers exist.

Real native/typed dispatch and table preview/commit/reload replace AUTO99's
helper-only assertions of unsupported protection. Ownership is compiled from sheets.
"""
import json

import pytest

from combat import ext, typed_executor as te
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.prepared_actions import SOURCE as READY
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

PREFIX = "tianxia.talent.harvesting_gathering."
BITTER = PREFIX + "bitter_spore_caution"
POULTICE = PREFIX + "first_aid_poultice"
HAZARD = PREFIX + "hazardous_harvest"
TALENTS = [BITTER, POULTICE, HAZARD]
QI = "resource:core.qi"
STAMINA = "resource:core.stamina"
ATTACKER = "actor:factory.hg-attacker"
DEFENDER = "actor:factory.hg-defender"
SOURCE = "test:poison_spore_harvest_named_attack"


def bundles(owner):
    return [compile_character(sheet(TALENTS if actor == owner else []), actor_id=actor)
            for actor in (ATTACKER, DEFENDER)]


def engine(owner, seed="HG99R1"):
    return Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=tuple(bundles(owner)),
        roster_setup={"primary_actor_ids": [ATTACKER, DEFENDER],
                      "team_by_actor": {ATTACKER: "team:a", DEFENDER: "team:b"},
                      "starting_positions": {ATTACKER: {"x": 3, "y": 6},
                                             DEFENDER: {"x": 4, "y": 6}}})


def packet(e, *, typed=False, source=SOURCE):
    attacker, defender = e.state.actors[ATTACKER], e.state.actors[DEFENDER]
    if typed:
        action = next(a for a in e.action_catalog.values() if a.owner_id == ATTACKER)
        action = action.model_copy(update={"source_definition_id": source})
        ctx = te.Context(e, attacker, action, None, {"numbers": {"save_dc": 100}}, [defender], defender)
        te.block_save(ctx, {"type": "save", "ability": "con", "on_fail": [
            {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 4},
             "damage_types": ["poison"]}], "on_success": []})
    else:
        e._roll_save(defender, "CON", 100, source, roll_context={"source_actor_id": ATTACKER})
    e._commit_damage(defender, 12, "POISON", source, ATTACKER, None, reaction_depth=0)


def test_compiled_modifier_ownership_is_local_to_the_learned_character():
    owned, other = bundles(ATTACKER)
    # Only Bitter-Spore retains descriptive modifier metadata. The two fully
    # dormant preparation talents intentionally compile no runtime ownership row.
    assert BITTER in {row["id"] for row in owned["modifiers"]}
    assert not set(TALENTS) & {row["id"] for row in other["modifiers"]}
    assert not any(set(TALENTS) & {row["id"] for row in bundle["modifiers"]}
                   for bundle in bundles(None))


@pytest.mark.parametrize("owner", [None, ATTACKER, DEFENDER])
@pytest.mark.parametrize("qi", [0, 30])
def test_ordinary_native_poison_save_and_damage_are_inert(owner, qi):
    e = engine(owner)
    target = e.state.actors[DEFENDER]
    target.resources[QI] = qi
    hp, resources = target.current_hp, dict(target.resources)
    packet(e)
    saves = [event for event in e.events if event.event_type == "SAVE_ROLLED"]
    assert saves[-1].payload["mode"] == "NORMAL"
    assert target.current_hp == hp - 12
    assert target.resources == resources
    assert not any(event.event_type == "QI_SPENT" for event in e.events)


@pytest.mark.parametrize("owner", [None, ATTACKER, DEFENDER])
def test_ordinary_typed_poison_tags_do_not_grant_harvesting_advantage(owner):
    e = engine(owner)
    packet(e, typed=True)
    saves = [event for event in e.events if event.event_type == "SAVE_ROLLED"]
    assert saves[-1].payload["mode"] == "NORMAL"


@pytest.mark.parametrize("qi", [0, 30])
def test_committed_enemy_poison_neither_reduces_damage_nor_spends_resources(qi):
    e = engine(DEFENDER)
    target = e.state.actors[DEFENDER]
    target.resources[QI] = qi
    hp, resources = target.current_hp, dict(target.resources)
    e._commit_damage(target, 12, "POISON", "test:ordinary_enemy_venom", ATTACKER, None, reaction_depth=0)
    assert target.resources == resources
    assert target.current_hp == hp - 12


def test_blocked_clauses_have_riders_and_no_active_effect_or_hook():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    for talent in TALENTS:
        row = authority["mechanics"][talent]
        assert row["effects"] == []
        assert not (row.get("modifier") or {}).get("effects")
        # The builder labels every reviewed record with riders CORE_WITH_RIDERS,
        # even when effects are empty. Empty effects, not that label, mean dormant.
        assert row["riders"] and row["coverage"] == "CORE_WITH_RIDERS"
    assert not {"gathering_poultice", "gathering_hazard_protection"} & ext.effects().keys()
    for bundle in bundles(DEFENDER):
        assert not any(row["source_definition_id"] in TALENTS for row in bundle["action_catalog"])
    for point in ("save", "save_mode", "damage_reduction", "damage_defenses"):
        assert not any(fn.__module__ == "combat.ext.harvesting_gathering" for fn in ext.subscribers(point))


@pytest.mark.parametrize("owner", [None, ATTACKER, DEFENDER])
@pytest.mark.parametrize("qi", [0, 30])
def test_poison_dispatch_table_commit_reload_and_replay(tmp_path, monkeypatch, owner, qi):
    # Test-only preparation emits ordinary poison through existing documented seams.
    # Native save/damage and table persistence run the production implementations.
    install(monkeypatch, "prepare_options", lambda *args: [{"option_id": "poison", "source_id": SOURCE,
            "label": "Ordinary poison attack", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *args: True)

    def resolve(e, actor, option, event, intent):
        target = e.state.actors[DEFENDER]
        if qi == 0:
            e._spend_resource(target, QI, target.resources[QI], "test:resource-setup")
        if owner == DEFENDER and qi == 0:
            # Public synthetic copies of AUTO99's old condition payloads. Preserve
            # their stored shape; removing the subscribers must make them inert.
            for condition_id, data in (
                ("condition:typed.gathering_first_aid_poultice", {"used": False}),
                ("condition:typed.gathering_hazardous_harvest", {"closed": False, "damage_type": "POISON"}),
            ):
                e._apply_condition(target, condition_id, "test:historical-preparation", DEFENDER,
                                   expires_on="UNTIL_REMOVED", data=data)
        packet(e)
        return True

    install(monkeypatch, "prepared_action", resolve)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles(owner), [ATTACKER, DEFENDER], {ATTACKER: "team:a", DEFENDER: "team:b"},
        {ATTACKER: {"x": 3, "y": 6}, DEFENDER: {"x": 4, "y": 6}},
        combat.factory_arenas()["battlefield:factory_pillar_arena"], [ATTACKER], [DEFENDER],
        control_modes={ATTACKER: "MANUAL", DEFENDER: "MANUAL"},
        match_seed="HG99R1-TABLE", display_name="Harvesting rider regression", maximum_rounds=20,
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    assert act(table, mid, READY)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = act(table, mid, "system:combat.hold_position")
    assert first["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**first["reaction"]["context"], "selection": "USE"}
    state, menu = first["state"], first["state"]["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"]
               if g["source_definition_id"] == "system:combat.hold_position")
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[DEFENDER]
    assert target.current_hp == before["actors"][DEFENDER]["current_hp"] - 12
    assert target.resources[QI] == qi
    assert target.resources.get(STAMINA) == before["actors"][DEFENDER]["resources"].get(STAMINA)
    saves = [event for event in loaded.engine.events if event.event_type == "SAVE_ROLLED"
             and event.source_definition_id == SOURCE]
    assert saves and saves[-1].payload["mode"] == "NORMAL"
    old_conditions = [c for c in target.conditions.values() if "gathering_" in c.condition_id]
    if owner == DEFENDER and qi == 0:
        assert len(old_conditions) == 2
        assert all(c.expires_on == "UNTIL_REMOVED" for c in old_conditions)
        assert not any((c.data or {}).get("used") for c in old_conditions)
    else:
        assert not old_conditions
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("seed", ["HG99-CONTROL-1", "HG99-CONTROL-2", "HG99-CONTROL-3"])
def test_nonowner_continuation_bytes_equal_without_harvesting_subscribers(monkeypatch, seed):
    actual = engine(None, seed)
    packet(actual)
    # Reference resolver surface excludes this lane's subscribers, as before AUTO99.
    for point in ("save", "save_mode", "damage_reduction", "damage_defenses"):
        monkeypatch.setitem(ext._HOOKS, point, [fn for fn in ext.subscribers(point)
                                              if fn.__module__ != "combat.ext.harvesting_gathering"])
    reference = engine(None, seed)
    packet(reference)

    def snapshot(e):
        return json.dumps({"state": e.state.model_dump(mode="json"),
                           "events": [v.model_dump(mode="json") for v in e.events],
                           "rolls": [v.model_dump(mode="json") for v in e.rolls]}, sort_keys=True)

    assert snapshot(actual) == snapshot(reference)
