"""Integrated Blade benefits use the same physical weapon after table reload."""
from types import SimpleNamespace

import pytest

from combat.ext import integrated_authority as ia
from combat.ext import kensei
from combat.ext.hand_occupancy import weapon_grips
from tests import worker2_support as w
from tests.test_redokensei_initiative_blade import setup, finish, KIT, BLADE, SWORD
from tests.hunt12_support import hit_dice

REFINED = ia.PREFIX + "refined_iron_fist"
HEAVENLY = ia.PREFIX + "heavenly_fist"


def test_integrated_blade_benefits_and_finesse_survive_commit_reload(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path, monkeypatch, features=(BLADE, REFINED, HEAVENLY), kit=KIT)
    w.turn(table, mid, w.OWNER)
    w.settle(table, mid, w.candidate(combat, mid, "Measured hit", target=w.FOE).candidate_id,
             choices={"choice:needle.blade_fist": "damage"})
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    weapon = next(a for a in engine.action_catalog.values() if a.owner_id == w.OWNER
                  and a.source_definition_id in weapon_grips(engine, owner))
    typed = weapon.parameters["typed"]
    assert typed["mundane"] is False
    assert typed["weapon"]["magical"] == typed["weapon"]["cultivation_powered"] == typed["weapon"]["adamantine"] == 1
    assert "FORCE" in ia.heavenly_types(SimpleNamespace(engine=engine, actor=owner, action=weapon, typed=typed), {}, ["SLASHING"])
    fists = [a for a in engine.action_catalog.values() if a.owner_id == w.OWNER
             and ".natural." in a.source_definition_id and a.parameters.get("typed", {}).get("weapon")]
    assert fists and all("Finesse" in a.parameters["typed"]["weapon"]["properties"] for a in fists)
    # Equal/lower Dexterity is still a legal printed choice, not just an optimizer.
    assert any(a.source_definition_id.endswith("#blade_fist_dex") for a in fists)
    assert any(a.source_definition_id.endswith("#integrated_dex") and a.owner_id == w.OWNER
               for a in engine.action_catalog.values())
    ctx = SimpleNamespace(engine=engine, actor=engine.state.actors[w.FOE], typed={"mundane": True})
    assert ia.heavenly_equipment(ctx, {"condition": "disarmed", "weapon": weapon.source_definition_id}, owner) is False
    ctx.typed["mundane"] = False
    assert ia.heavenly_equipment(ctx, {"condition": "disarmed", "weapon": weapon.source_definition_id}, owner) is None


@pytest.mark.parametrize("higher,artifact", [(False, False), (True, False), (False, True)])
def test_heavenly_object_permissions_are_per_hit_not_saved_defense_edits(tmp_path, higher, artifact):
    def objects(arena):
        arena["map_objects"] = [{"id": 610, "kind": "crate", "x": 2, "y": 6,
            "hp": 1000, "ac": 1, "threshold": 100, "unattended": True, "artifact": artifact,
            "source_cl": 99 if higher else 1, "resist": ["SLASHING"]}]
    def reliable(bundles):
        from combat.canonical import canonical_sha256
        for action in bundles[0]["action_catalog"]:
            if action["parameters"].get("object_attack"):
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundles[0].pop("bundle_sha256", None)
        bundles[0]["bundle_sha256"] = canonical_sha256(bundles[0])
    combat, table, mid = w.fixture(tmp_path, [], owner_features=[BLADE, REFINED, HEAVENLY],
        owner_path="Body Refining", primary="Stamina", cl=18, owner_kit=KIT,
        battlefield_transform=objects, bundle_transform=reliable)
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == w.OWNER
        and a.parameters.get("object_attack") and a.parameters["typed"]["object_weapon_group"] != "unarmed")
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id
                     and c.target_ids == ("object:map.610",))
    w.settle(table, mid, candidate.candidate_id)
    engine = w.reload(tmp_path, mid)
    obj = engine.state.objects["object:map.610"]
    raw = sum(int(r.total) for r in engine.rolls if ":object:" in str(r.reason) and str(r.reason).startswith("DAMAGE:"))
    assert raw > 0
    assert obj.current_hp == (1000 if higher or artifact else 1000 - 2 * raw)
    assert obj.damage_threshold == 100
    assert "SLASHING" in obj.component["resist"]


def test_initiative_draw_strikes_before_first_enemy_turn(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = setup(tmp_path, monkeypatch, features=(SWORD, BLADE), kit=KIT)
    prompts = finish(combat, table, mid, "strike")
    assert any(p["context"]["reaction_source_id"] == "choice:needle.kensei_weapon" for p in prompts)
    engine = w.reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == w.OWNER)
    first_turn = next(e for e in engine.events if e.event_type == "TURN_STARTED")
    assert engine.events.index(attack) < engine.events.index(first_turn)
    assert weapon_grips(engine, engine.state.actors[w.OWNER])


def test_initiative_manifest_moves_recorded_blade_out_of_its_old_location(tmp_path, monkeypatch):
    from combat import ext, carry
    ext.effects()
    def misplaced(engine):
        actor = engine.state.actors.get(w.OWNER)
        if actor is None:
            return
        item = next(i for i in carry.carrying_of(engine, w.OWNER)["items"] if i.get("weapon_action"))
        engine._apply_condition(actor, "condition:typed.disarmed", "synthetic:misplaced", w.FOE,
            expires_on="UNTIL_REMOVED", data={"item_key": item["key"], "disables_action": item["weapon_action"],
            "dropped_at": {"x": 10, "y": 6, "z": 0}})
        carry.refresh(engine, actor, "synthetic:misplaced")
    monkeypatch.setitem(ext._HOOKS, "match_start", [*ext._HOOKS["match_start"], misplaced])
    combat, table, mid = setup(tmp_path, monkeypatch, features=(SWORD, BLADE), kit=KIT)
    initial = w.reload(tmp_path, mid)
    assert not weapon_grips(initial, initial.state.actors[w.OWNER])
    prompts = finish(combat, table, mid, "strike")
    options = next(p["choice"]["options"] for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.kensei_weapon")
    assert any("Manifest" in str(option) for option in options)
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    assert weapon_grips(engine, owner)
    assert not any(c.source_definition_id == "synthetic:misplaced" for c in owner.conditions.values())


def test_surprised_scene_has_no_sword_choice_or_later_activation(tmp_path, monkeypatch):
    from combat import ext
    ext.effects()
    def surprise(engine):
        actor = engine.state.actors.get(w.OWNER)
        if actor:
            engine._apply_condition(actor, "condition:surprised", "synthetic:surprise", w.FOE,
                                    expires_on="START_OF_SOURCE_NEXT_TURN")
    monkeypatch.setitem(ext._HOOKS, "match_start", [*ext._HOOKS["match_start"], surprise])
    combat, table, mid = setup(tmp_path, monkeypatch)
    engine = w.reload(tmp_path, mid)
    if engine.state.setup_tasks:
        prompts = finish(combat, table, mid, "ac")
        assert not any(p["context"]["reaction_source_id"] == "choice:needle.sword_draws_before_thought" for p in prompts)
    w.turn(table, mid, w.OWNER)
    engine = w.reload(tmp_path, mid)
    assert not engine.state.setup_tasks
    assert not any(m.source_definition_id == SWORD for m in engine.state.actors[w.OWNER].modifiers.values())


def test_wall_weapon_permissions_survive_reload_and_preserve_immunity(tmp_path):
    combat, table, mid = w.fixture(tmp_path, [], owner_features=[BLADE, REFINED, HEAVENLY],
        owner_path="Body Refining", primary="Stamina", cl=18, owner_kit=KIT)
    w.settle(table, mid, table.state(mid)["menu"]["end_turn"], choices={})
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    wall = next(a for a in engine.action_catalog.values() if a.owner_id == w.OWNER and a.parameters.get("wall_attack"))
    assert wall.parameters["typed"]["mundane"] is False
    ctx = SimpleNamespace(engine=engine, actor=owner, action=wall, typed=wall.parameters["typed"])
    stats = {"resist": ["SLASHING", "FIRE"], "immune": ["FORCE"], "vulnerable": ["COLD"]}
    zone = SimpleNamespace(trigger_profile={"numbers": {"cl": 10}})
    answer = ia.heavenly_wall_defenses(ctx, zone, stats)
    assert answer["damage_multiplier"] == 2 and answer["resist"] == ["FIRE"]
    assert answer["immune"] == ["FORCE"] and stats["resist"] == ["SLASHING", "FIRE"]
    zone.trigger_profile["numbers"]["cl"] = 99
    assert ia.heavenly_wall_defenses(ctx, zone, stats) is None
