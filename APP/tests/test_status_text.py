"""Source-backed tooltips through the table boundary, including the owner's portable pool."""
import copy
import json
import os
import subprocess

import pytest

from combat.condition_text import all_conditions
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.status_text import describe, duration_text, printed_excerpt
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_prefight import SHEET as MELD_SHEET
from tests.status_text_support import ROOT, _install, _rows, _tooltip_table, assert_specific_status



@pytest.fixture
def synthetic_meld_rules(tmp_path, monkeypatch):
    """Stable projection inputs even when the public export redacts rule prose."""
    from tests.record_display_support import install_display_rules
    rules = {
        "TAL_DARK_CLEARSIGHT": (
            "### Clearsight - Meld\nThe target is immune to negative effects created by your Darkness talents. "
            "Clearsight does not automatically grant sight through Darkness."),
        "TAL_DARK_HIDE_IN_DARKNESS": (
            "### Hide in Darkness - Meld\nThe target can Hide in your Darkness even while clearly visible. "
            "This overrides the ordinary Hide action's line-of-sight requirement."),
    }
    install_display_rules(tmp_path, monkeypatch, rules)


def test_meld_tooltip_uses_the_selected_printed_option_at_the_table_and_after_reload(tmp_path, synthetic_meld_rules):
    sheet = copy.deepcopy(MELD_SHEET)
    sheet["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_DARK_HIDE_IN_DARKNESS")
    _install(tmp_path, "meld", sheet)
    _install(tmp_path, "foe", SHEET)
    bundle = compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + "meld")
    picks = [option["action_id"] for option in bundle["prefight"]["options"]
             if option["name"] in {"Meld: Clearsight (Persistent)", "Meld: Hide in Darkness"}]
    assert len(picks) == 2
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=["meld"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "foe"],
                                      prefight={FACTORY_ACTOR_PREFIX + "meld": picks}, match_seed="P6-MELD")["match_id"]
    table = TabletopService(combat, tmp_path)
    rows = _rows(table, combat, mid)
    meld = next(row for row in rows if row.get("display_name", "").startswith("Meld: Clearsight"))
    assert "immune to negative effects created by your Darkness talents" in meld["rule_text"]
    assert "does not automatically grant sight" in meld["rule_text"]
    assert "Applied by" in meld["detail"] and "Clearsight" in meld["source_ability"]
    assert "table applies this Meld" in meld["handling"]
    hide = next(row for row in rows if row.get("display_name", "").startswith("Meld: Hide in Darkness"))
    assert "even while clearly visible" in hide["rule_text"]
    assert "Clearsight does not" not in hide["rule_text"]
    assert hide["duration"] == "while concentrating, up to 1 hour"
    # Execute the actual BroadcastChannel message builder and sheet renderer:
    # matching JS source strings alone cannot prove the element has a tooltip.
    rendered = subprocess.run(
        ["node", "--test", str(ROOT / "tests/sheet_status_tooltips_dom.test.mjs")],
        env={**os.environ, "P6_TOOLTIP_ROWS": json.dumps([meld, hide])},
        capture_output=True, text=True,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    # The same detail is shipped by conditionText to both map hover and actorMessage.
    js = (ROOT / "static/tabletop/tabletop.js").read_text()
    assert "if (row?.detail) return row.detail" in js
    assert js.count("text: conditionText(row)") >= 2
    combat.local_step(mid)  # normal table commit
    resumed = CombatService(ROOT, tmp_path)
    reloaded = _rows(TabletopService(resumed, tmp_path), resumed, mid)
    assert next(row for row in reloaded if row.get("display_name") == meld["display_name"])["detail"] == meld["detail"]


def test_hide_in_darkness_is_an_option_rule_not_the_meld_procedure(synthetic_meld_rules):
    text = printed_excerpt("TAL_DARK_HIDE_IN_DARKNESS", "Meld: Hide in Darkness")
    assert "even while clearly visible" in text and "line-of-sight requirement" in text
    assert "10 minutes" not in text


def test_a_failing_presentation_hook_does_not_write_fight_events(tmp_path, monkeypatch):
    from combat import ext

    _install(tmp_path, "meld", MELD_SHEET)
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=["meld"], match_seed="P6-BROKEN-DESCRIPTOR")["match_id"]
    table = TabletopService(combat, tmp_path)
    _rows(table, combat, mid)  # load the ordinary providers first

    def broken(engine, holder, row, data):
        if row.get("condition_id") == "condition:typed.meld_set":
            raise ValueError("deliberately broken presentation provider")

    monkeypatch.setitem(ext._HOOKS, "status_description", [*ext._HOOKS["status_description"], broken])
    rows = _rows(table, combat, mid)  # also checks byte-identical engine state/events
    assert next(row for row in rows if row.get("display_name", "").startswith("Meld: Clearsight"))["rule_text"]


@pytest.mark.parametrize("expiry, expected", [
    ("START_OF_SOURCE_NEXT_TURN", "until the start of Mei's next turn"),
    ("START_OF_TARGET_NEXT_TURN", "until the start of Mei's or Bo's next turn, whichever comes first"),
    ("END_OF_HOLDER_NEXT_TURN", "until the end of Bo's next turn"),
    ("STAND_UP", "until it stands up"),
    ("UNTIL_REMOVED", "until removed"),
])
def test_expiry_in_words(expiry, expected):
    assert duration_text(expiry, {}, {}, "Mei", "Bo", {}, None) == expected


def test_concentration_and_minutes_are_explained():
    assert duration_text("CONCENTRATION_END", {}, {"duration": {"kind": "minutes", "amount": 1}},
                         "Mei", "Bo", {}, None) == "while concentrating, up to 1 minute"


def test_instance_rule_overrides_the_condition_category():
    from types import SimpleNamespace

    actor = SimpleNamespace(entity_id="bo", turns_started=3)
    engine = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={"bo": actor}))
    row = {"condition_id": "condition:typed.concentration_mode", "expires_on": "END_OF_TURN_AT:bo:4"}
    text = describe(engine, actor, row, {"rule": {"concentration_mode": "DISADVANTAGE", "next": True}},
                    {"bo": "Bo"}, {}, condition_rules=all_conditions())
    assert "Disadvantage on Concentration saving throws" in text["rule_text"]
    assert "used up by the next applicable roll" in text["rule_text"]
    assert text["duration"] == "until the end of Bo's next turn"


def test_suppressed_benefit_status_does_not_describe_its_stored_rule_as_active():
    from types import SimpleNamespace

    actor = SimpleNamespace(entity_id="bo", turns_started=3)
    engine = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={"bo": actor}))
    row = {"condition_id": "condition:typed.suppressed.d20_floor", "display_name": "Complete Mandala Auspice",
           "expires_on": "UNTIL_REMOVED"}
    text = describe(engine, actor, row,
                    {"label": "Complete Mandala Auspice", "reading": "A low d20 roll counts as a 10.",
                     "rule": {"d20_floor": {"floor": 10}}},
                    {"bo": "Bo"}, {}, condition_rules=all_conditions())
    assert text["display_name"] == "Suppressed: Complete Mandala Auspice"
    assert text["rule_text"] == "This effect is temporarily suppressed and provides no benefit."
    assert "counts as a 10" not in text["detail"]
    assert "restores it when the suppression expires" in text["detail"]


def test_exhaustion_names_the_source_ability_owner_even_when_the_marker_is_filed_under_its_holder():
    from types import SimpleNamespace

    source = "action:test.exhaust"
    engine = SimpleNamespace(action_catalog={source: SimpleNamespace(owner_id="mei", parameters={})},
        state=SimpleNamespace(actors={"mei": SimpleNamespace(display_name="Mei"), "bo": SimpleNamespace(display_name="Bo")}))
    row = {"condition_id": "condition:typed.exhaustion", "source_definition_id": source,
           "source_actor_id": "bo", "expires_on": "UNTIL_REMOVED"}
    text = describe(engine, SimpleNamespace(entity_id="bo"), row, {"level": 2}, {"mei": "Mei", "bo": "Bo"}, {source: "Darklands Cry"})
    assert text["applied_by"] == "Mei"
    assert "Exhaustion level 2" in text["rule_text"] and "from Darklands Cry" in text["detail"]


def test_terrain_tooltip_has_rule_provenance_and_lifetime_and_resources_do_not_share_the_fallback(tmp_path):
    _install(tmp_path, "left", SHEET)
    combat = CombatService(ROOT, tmp_path)
    document = combat.tabletop_maps.save({"display_name": "P6 ground", "width_squares": 18, "height_squares": 12,
                                         "materials": [{"material": "terrain:bamboo thicket", "cells": [[3, 3], [3, 4], [4, 4]]}]})
    mid = combat.create_factory_match(project_ids=["left"], arena_id=f"battlefield:map.{document['map_id']}", match_seed="P6-GROUND")["match_id"]
    state = TabletopService(combat, tmp_path).state(mid)
    zones = state["presentation"].get("zones") or []
    assert zones
    for row in zones:
        assert row["rule_text"] and row["detail"] and row["duration"]
    js = (ROOT / "static/tabletop/zones.js").read_text()
    assert "if (zone?.detail) lines.push(zone.detail)" in js
    for path in ["static/tabletop/tabletop.js", "static/tabletop/sheet.js"]:
        assert "No automatic effect; see its source" not in (ROOT / path).read_text()


def test_edge_before_blood_table_tooltip_states_actual_resistance_limit(tmp_path, monkeypatch):
    from combat.typed_executor import mark_condition_id

    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine._apply_condition(actor, mark_condition_id("Edge Before Blood", actor.entity_id),
                            "action:old.set_edge", actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN")
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if "edge_before_blood" in r["condition_id"])
    assert row["handling"] == ("On the first weapon hit, the table ignores resistance to the weapon's damage type, "
        "including magical resistance, because it cannot distinguish magical from nonmagical resistance. "
        "Immunity is unchanged. The printed rule requires GM approval to ignore magical resistance.")
    assert row["handling"] in row["detail"]
    assert "Magical resistance remains a GM ruling" not in row["detail"]


@pytest.mark.parametrize("owner_turn, expected_turn", [(3, "next turn"), (4, "current turn")])
def test_zone_table_tooltip_anchors_expiry_to_owner_not_current_actor(tmp_path, monkeypatch, owner_turn, expected_turn):
    from combat.gate2_runtime_models import ZoneState
    from combat.ext.effect_durations import turn_ended

    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    owner = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    other = next(a for a in engine.state.actors.values() if a.entity_id != owner.entity_id)
    owner.turns_started = owner_turn
    other.turns_started = 9
    engine.state.current_actor_id = other.entity_id
    engine.state.zones["zone:test.deadline"] = ZoneState(
        zone_id="zone:test.deadline", source_definition_id="action:old.area", owner_id=owner.entity_id,
        center=owner.position, radius_cells=1, affected_cells=(owner.position,), concentration_link=False,
        created_round=engine.state.round_number,
        trigger_profile={"kind": "TYPED", "name": "Protective area", "end_after_owner_turn": 4})
    row = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == "zone:test.deadline")
    assert row["duration"] == f"until the end of {owner.display_name}'s {expected_turn}"
    assert f"Lasts {row['duration']}." in row["detail"]
    turn_ended(engine, other)
    assert engine.state.zones["zone:test.deadline"].active
    owner.turns_started = 4
    turn_ended(engine, owner)
    assert not engine.state.zones["zone:test.deadline"].active


def test_old_status_table_tooltips_have_player_readings_and_no_internal_sources(tmp_path, monkeypatch):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    for cid in ("bound_hand", "cannot_teleport"):
        engine._apply_condition(actor, "condition:typed." + cid, "action:typed.old.internal_id", actor.entity_id,
                                expires_on="UNTIL_REMOVED")
    rows = {r["condition_id"]: r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]}
    hand = rows["condition:typed.bound_hand"]
    seal = rows["condition:typed.cannot_teleport"]
    assert "until the creature escapes" in hand["rule_text"]
    assert "applies Disadvantage to all of that creature's attack rolls" in hand["rule_text"]
    assert "blocks its own self-teleport abilities" in seal["rule_text"]
    assert "GM handles the printed restrictions on portals, extradimensional storage, pocket spaces" in seal["rule_text"]
    for row in (hand, seal):
        assert row["source_ability"] == "Source ability unavailable in this saved fight"
        for internal in ("combat/", "worker", "w2-support", "2026-09-28", "action:typed", "internal_id", "_rule"):
            assert internal not in row["detail"]


@pytest.mark.parametrize("reading, expected", [
    ("Disadvantage on attacks using the bound hand (the table applies it to all attack rolls); combat/ext/thread_lines.py.",
     "Disadvantage on attacks using the bound hand (the table applies it to all attack rolls)."),
    ("Dimensional Seal (Space, worker w2-support 2026-09-28): blocks self-teleport abilities (combat/typed_executor.py block_movement).",
     "Dimensional Seal (Space): blocks self-teleport abilities."),
])
def test_saved_readings_strip_annotations_but_keep_mechanical_limits_at_table(tmp_path, monkeypatch, reading, expected):
    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    engine._apply_condition(actor, "condition:typed.old_saved_status", "action:old.unknown", actor.entity_id,
                            expires_on="UNTIL_REMOVED", data={"reading": reading})
    row = next(r for a in table.state(mid)["presentation"]["actors"] for r in a["conditions"]
               if r["condition_id"] == "condition:typed.old_saved_status")
    assert row["rule_text"] == expected
    assert expected in row["detail"]
    assert "combat/" not in row["detail"] and "worker" not in row["detail"] and "action:old" not in row["detail"]


def test_equipment_and_death_statuses_have_specific_table_rules(tmp_path, monkeypatch):
    from tests.test_starting_loadout import owner, W, SHIELD

    # Starting loadouts create a held focus and a carried shield in real matches.
    for project, items, expected in (
        ("focus", [W + "jian", "tianxia.mortal.focus.qi_focus_jade_orb"], "held_object"),
        ("shield", [W + "qiang", SHIELD], "shield_equipped"),
    ):
        _install(tmp_path, project, owner(items))
        combat = CombatService(ROOT, tmp_path)
        mid = combat.create_factory_match(project_ids=[project], match_seed="P6-" + project)["match_id"]
        rows = _rows(TabletopService(combat, tmp_path), combat, mid)
        row = next(r for r in rows if r["condition_id"] == "condition:typed." + expected)
        assert_specific_status(row)
        assert ("holds" if expected == "held_object" else "shield") in row["rule_text"].lower()

    table, mid, engine = _tooltip_table(tmp_path, monkeypatch)
    actor = engine.state.actors[FACTORY_ACTOR_PREFIX + "left"]
    # These producers need specialized feature setups; retain their actual instance data.
    sources = {
        "body_scene": ("system:body_modes_scene_resources", {"source": "body:test", "scene_id": "match:test", "source_cl": 1, "label": "Body scene"}),
        "blacksmith_current_item": ("action:typed.blacksmith.current_item.equipment", {"owner": actor.entity_id, "key": "hammer", "kind": "tool", "label": "Current workpiece: hammer"}),
        "treasure_armor_element_choice": ("tianxia.treasure.armor_enhancement.sovereign_resistance_matrix", {"feature_id": "tianxia.treasure.armor_enhancement.sovereign_resistance_matrix", "item_key": "armor", "damage_types": ["fire", "cold"]}),
    }
    for name, (source, data) in sources.items():
        engine._apply_condition(actor, "condition:typed." + name, source, actor.entity_id,
                                expires_on="UNTIL_REMOVED", data=data)
    engine._commit_damage(actor, actor.maximum_hp * 3, "FORCE", "system:damage", actor.entity_id, None, reaction_depth=0)
    rows = _rows(table, table.combat, mid)
    for name, snippet in (("body_scene", "per-scene resources"), ("blacksmith_current_item", "workpiece"),
                          ("treasure_armor_element_choice", "damage types"), ("death_finalized", "dead")):
        row = next(r for r in rows if r["condition_id"] == "condition:typed." + name)
        assert_specific_status(row)
        assert snippet in row["rule_text"].lower()


def test_weapon_readiness_descriptions_survive_table_commit_reload_and_event_projection(tmp_path):
    from tests.test_lock7_punishment import fight, turn, FOE

    combat, table, mid = fight(tmp_path, owns=False)
    turn(table, mid, FOE)
    for held, verb in ((False, "stows"), (True, "draws")):
        state = table.state(mid)
        engine = combat._load_session(mid).engine
        candidate = next(candidate for candidate in engine.legal_candidates()
                         if candidate.actor_id == FOE
                         and (action := engine.action_catalog.get(candidate.source_definition_id)) is not None
                         and (grip := action.parameters.get("equipment_grip"))
                         and grip["held"] == held)
        result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, state["last_sequence"])
        assert result["status"] == "COMMITTED"
        reloaded = CombatService(ROOT, tmp_path)
        session = reloaded._load_session(mid)
        engine = session.engine
        assert session.verify()["status"] == "PASS"
        rows = _rows(TabletopService(reloaded, tmp_path), reloaded, mid)
        assert not any(row.get("condition_id") == "condition:typed.equipment_grip" for row in rows)
        assert engine.state.actors[FOE].equipment_readiness[grip["weapon"]] == int(held)
        changes = [e for e in engine.events if e.event_type == "EQUIPMENT_READINESS_SET"
                   and e.source_definition_id == candidate.source_definition_id]
        assert len(changes) == 1
        assert f" {verb} " in changes[0].payload["log"]
