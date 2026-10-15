"""Native Starbolt creature delivery, acquired through the Stars base packet.

No scene alignment, defenses, marks or ability effects are injected. Unmodeled
sky/anchor/map facts and object marks are deliberately not certified here.
"""
import hashlib
import json

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from sphere_component_authority import attach_sphere_automatic_component_receipt
from combat.ext import stars
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, resolve, action_sender, turn
from tests.h1_support import ROOT

BOLT = "STARS_BASE_STARBOLT"
SPHERE = "tianxia.sphere.stars"
TYPE_CHOICE = "choice:needle.starbolt_damage"


def acquired_starbolt(doc, actor_id):
    if actor_id != LEFT:
        return
    parent = CanonicalCatalogAuthorityService(ROOT).get_sphere(SPHERE)
    ledger = {}
    packet = attach_sphere_automatic_component_receipt(ledger, parent, {
        "event_id": "starbolt-regression-acquisition", "legal_channel": "sphere_acquisition",
        "advancement": {"target_cl": 1},
    })
    assert BOLT in packet["component_ids"]
    doc["spheres_and_talents"] = {
        "sphere_record_ids": [SPHERE], "learned_talent_record_ids": [],
        "automatic_sphere_component_receipts": ledger["automatic_sphere_component_receipts"],
        "automatic_sphere_components": ledger["automatic_sphere_components"],
        "automatic_sphere_component_record_ids": packet["component_ids"],
    }


def native_fight(tmp_path, **kwargs):
    kwargs.setdefault("left_attack_bonus", 100)
    return fight(tmp_path, sheet_edit=acquired_starbolt, **kwargs)


@pytest.mark.parametrize("cl,count", [(1, 1), (4, 1), (5, 2), (10, 2), (11, 3), (16, 3), (17, 4), (20, 4)])
def test_acquired_base_scales_and_player_selects_damage_then_optional_mark(tmp_path, cl, count):
    combat, table, mid = native_fight(tmp_path, cl=cl)
    _, prompts = resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT), {
        TYPE_CHOICE: ["COLD"], "choice:needle.starbolt_mark": [],
    })
    choice = next(p for p in prompts if p["context"]["reaction_source_id"] == TYPE_CHOICE)
    assert {o["id"] for o in choice["choice"]["options"]} == {"RADIANT", "FORCE", "COLD"}
    assert all(text in str(choice) for text in ("Starbolt", "Visitor", "Action", "0 Cultivation Points"))
    engine = reload(combat, mid)
    roll = next(r for r in engine.rolls if r.reason.startswith("DAMAGE:"))
    assert roll.expression == f"{count}d8+2"
    damage = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED")
    assert damage.payload["damage_type"] == "COLD"
    assert not stars.bears_mark(engine.state.actors[RIGHT], LEFT)
    assert not engine.state.actors[LEFT].action_available
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 100


@pytest.mark.parametrize("auto", [False, True])
def test_allied_creature_is_reachable_and_mark_survives_cold_reload(tmp_path, auto):
    combat, table, mid = native_fight(tmp_path, right_team="team:factory", extra_witness=True)
    _, prompts = resolve(action_sender(combat, table, mid, "Starbolt", ai=auto, target_id=RIGHT))
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert stars.bears_mark(engine.state.actors[RIGHT], LEFT)
    assert not stars.bears_mark(engine.state.actors[RIGHT], RIGHT)
    assert any(p["context"]["reaction_source_id"] == TYPE_CHOICE for p in prompts) == (not auto)
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not stars.bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT)


def test_unowned_character_does_not_get_starbolt_and_unknown_alignment_does_not_extend_range(tmp_path):
    combat, table, mid = native_fight(tmp_path, positions={LEFT: {"x": 0, "y": 6}, RIGHT: {"x": 19, "y": 6}})
    engine = reload(combat, mid)
    markers = engine.typed_passive_rows
    assert len([r for r in markers[LEFT] if r.get('block') == 'stars' and r.get('kind') == 'starbolt']) == 1
    assert not any(r.get('block') == 'stars' and r.get('kind') == 'starbolt' for r in markers.get(RIGHT, []))
    assert not any(RIGHT in o.get("target_ids", []) for g in table.state(mid)["menu"]["actions"]
                   if g["label"].startswith("Starbolt") for o in g["options"])
    assert not any(engine.action_catalog[aid].parameters.get("typed", {}).get("source") == BOLT
                   for aid in engine.state.actors[RIGHT].action_ids)


def test_miss_does_not_choose_damage_or_apply_mark(tmp_path):
    combat, table, mid = native_fight(tmp_path, left_attack_bonus=-100)
    _, prompts = resolve(lambda a: act(table, mid, "Starbolt", a, target_id=RIGHT))
    assert not any(p["context"]["reaction_source_id"] in {TYPE_CHOICE, "choice:needle.starbolt_mark"}
                   for p in prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 1000
    assert not stars.bears_mark(engine.state.actors[RIGHT], LEFT)


def test_team_neutral_attack_keeps_charm_guard(tmp_path):
    combat, table, mid = native_fight(tmp_path, cause=[{
        "type": "condition", "condition": "charmed", "applies_to": "target", "duration": "until_removed",
    }])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a, target_id=LEFT))
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert any(c.condition_id == "condition:typed.charmed" and c.source_actor_id == RIGHT
               for c in engine.state.actors[LEFT].conditions.values())
    assert not any(RIGHT in o.get("target_ids", []) for g in table.state(mid)["menu"]["actions"]
                   if g["label"].startswith("Starbolt") for o in g["options"])


def test_controlling_text_hash_is_decoded_text_not_old_source_metadata():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[BOLT]
    assert hashlib.sha256(text.encode()).hexdigest() == "cf365810eddf0e0effda8e01bddddae4e7d8628b6ac660e899ba3a3705f7973d"


def test_native_acquisition_retains_starbolt_consumers_without_legacy_feature_shard(tmp_path, monkeypatch):
    """Actual acquisition remains authoritative when an optional marker shard is absent."""
    from combat import typed_reactions
    rules = json.loads(json.dumps(typed_reactions.rules()))
    rules['features'].pop(BOLT, None)
    path = tmp_path / 'portable-feature-blocks.json'
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(typed_reactions, 'RULES_PATH', path)
    monkeypatch.setattr(typed_reactions, '_CACHE', {})
    combat, table, mid = native_fight(tmp_path)
    engine = reload(combat, mid)
    assert len([r for r in engine.typed_passive_rows[LEFT]
                if r.get('feature_id') == BOLT and r.get('kind') == 'starbolt']) == 1
    assert not any(r.get('feature_id') == BOLT for r in engine.typed_passive_rows.get(RIGHT, []))
    _, prompts = resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT),
        {TYPE_CHOICE: ['COLD'], 'choice:needle.starbolt_mark': ['MARK']})
    assert any(p['context']['reaction_source_id'] == TYPE_CHOICE for p in prompts)
    engine = reload(combat, mid)
    assert stars.bears_mark(engine.state.actors[RIGHT], LEFT)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.payload.get('damage_type') == 'COLD'
               and RIGHT in e.target_ids for e in engine.events)
