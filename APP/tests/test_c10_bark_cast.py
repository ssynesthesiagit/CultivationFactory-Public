"""Bark-Splitting Cast at the table, including persisted object damage and AI."""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import FACTORY_ACTOR_PREFIX as PREFIX
from tests.test_c10_review_fixup import make_table, end_until_hero, act, reload_check
from tests.test_sysv2_objects import build, fight, candidates, force_d20, use

BARK = "TAL_AXES_BARK_SPLITTING_CAST"
AXES = "tianxia.sphere.axes"
AXE = "tianxia.mortal.weapon.fu"
CAST = "TAL_AXES_CAST_AXE"
NAME = "Fu (Short Axe) thrown: Cast Axe: Splinter Cast + Bark-Splitting Cast (object)"
SHOCK_NAME = "Fu (Short Axe) thrown: Cast Axe: Shock Cast + Bark-Splitting Cast (object)"


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("natural", [1, 15, 20])
def test_bark_cast_long_range_object_damage_commits_and_reloads(tmp_path, monkeypatch, mode, natural):
    original = DeterministicRollAuthority.d20
    def forced(self, **kwargs):
        roll = original(self, **kwargs)
        return roll.model_copy(update={"natural_result": natural, "total": natural + kwargs.get("modifier", 0),
                                       "dice": (natural,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", forced)
    service, table, mid = make_table(tmp_path, [BARK], AXES, mode, items=(AXE,), objects=[
        {"id": 1, "kind": "crate", "x": 9, "y": 3, "hp": 999, "ac": 1}])
    end_until_hero(table, mid)
    before = reload_check(service, mid).state.objects["object:map.1"].current_hp
    prompts = act(service, table, mid, mode, monkeypatch, NAME)
    assert not prompts  # Selecting this action opts into normal-range treatment.
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.target_ids == ("object:map.1",)]
    assert len(attacks) == 1 and attacks[0].payload["mode"] == "NORMAL"
    rolls = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and "axes_bark_cast" in r.reason]
    if natural == 1:
        assert not rolls and engine.state.objects["object:map.1"].current_hp == before
    else:
        assert len(rolls) == 1
        assert len(rolls[0].dice) == (4 if natural == 20 else 2)
        assert rolls[0].total == sum(rolls[0].dice) + 2 + 4  # STR and Splinter Cast PB once, even on a critical.
        assert engine.state.objects["object:map.1"].current_hp == before - rolls[0].total
    assert not engine.state.actors[PREFIX + "aaaaaaaa"].action_available


def test_bark_cast_requires_talent_held_axe_unattended_target_and_long_range():
    objects = [{"id": 1, "kind": "crate", "x": 9, "y": 6},
               {"id": 2, "kind": "crate", "x": 10, "y": 6, "unattended": False},
               {"id": 3, "kind": "crate", "x": 16, "y": 6}]
    engine = fight(build(AXES, [BARK], axe=True, base=[CAST]), objects=objects)
    assert candidates(engine, NAME, "object:map.1")
    assert not candidates(engine, NAME, "object:map.2")
    assert not candidates(engine, NAME, "object:map.3")  # 65 feet, beyond Fu's 60-foot long range.
    assert all(c.target_ids[0].startswith("object:") for _, c in candidates(engine, NAME))
    assert not candidates(fight(build(AXES, [], axe=True, base=[CAST]), objects=objects), NAME)
    assert not candidates(fight(build(AXES, [BARK], axe=False, base=[CAST]), objects=objects), NAME)
    action = next(a for a in engine.action_catalog.values() if a.display_name == NAME)
    engine._apply_condition(engine.state.actors[action.owner_id], "condition:typed.disarmed", "test", action.owner_id,
                            expires_on="UNTIL_REMOVED", data={"disables_action": action.parameters["typed"]["delivered_by"].split("#")[0]})
    assert not candidates(engine, NAME)


def test_bark_cast_keeps_damage_threshold_and_creature_cast_unchanged():
    engine = fight(build(AXES, [BARK], axe=True, base=[CAST]), objects=[
        {"id": 1, "kind": "crate", "x": 9, "y": 6, "hp": 999, "threshold": 999}])
    force_d20(engine, 15, 19)
    use(engine, NAME, "object:map.1")
    assert engine.state.objects["object:map.1"].current_hp == 999
    creature_casts = [a for a in engine.action_catalog.values() if "Cast Axe:" in a.display_name and a.target_kind == "HOSTILE_ENTITY"]
    assert creature_casts
    assert all(a.parameters["typed"]["weapon"]["damage"]["count"] == 1 for a in creature_casts)
    assert all(a.parameters["typed"]["range_ft"] == 20 for a in creature_casts)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("kind,material", [("wall_section", "wood"), ("barricade", "wood"),
                                          ("door", "wood"), ("gate", "wood"),
                                          ("rope", "rope"), ("banner", "wood")])
def test_attended_explicit_bark_targets_commit_and_reload(tmp_path, monkeypatch, mode, kind, material):
    original = DeterministicRollAuthority.d20
    def hit(self, **kwargs):
        roll = original(self, **kwargs)
        return roll.model_copy(update={"natural_result": 15, "total": 15 + kwargs.get("modifier", 0), "dice": (15,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    service, table, mid = make_table(tmp_path, [BARK], AXES, mode, items=(AXE,), objects=[
        {"id": 1, "kind": kind, "material": material, "unattended": False,
         "blocks": False, "x": 9, "y": 3, "hp": 999, "ac": 1}])
    end_until_hero(table, mid)
    before = reload_check(service, mid).state.objects["object:map.1"].current_hp
    assert not act(service, table, mid, mode, monkeypatch, NAME)
    engine = reload_check(service, mid)
    obj = engine.state.objects["object:map.1"]
    assert not obj.unattended
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.target_ids == (obj.object_id,)]
    assert len(attacks) == 1 and attacks[0].payload["mode"] == "NORMAL"
    damage = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and "axes_bark_cast" in r.reason]
    assert len(damage) == 1 and len(damage[0].dice) == 2
    assert damage[0].total == sum(damage[0].dice) + 2 + 4
    assert obj.current_hp == before - damage[0].total


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("unattended", [True, False])
def test_explicit_vine_cast_commits_reloads_and_retains_object_rules(tmp_path, monkeypatch, mode, unattended):
    original = DeterministicRollAuthority.d20
    def hit(self, **kwargs):
        roll = original(self, **kwargs)
        return roll.model_copy(update={"natural_result": 15, "total": 15 + kwargs.get("modifier", 0), "dice": (15,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    service, table, mid = make_table(tmp_path, [BARK], AXES, mode, items=(AXE,), objects=[
        {"id": 1, "kind": "vine", "unattended": unattended, "x": 9, "y": 3, "hp": 999, "ac": 1}])
    end_until_hero(table, mid)
    before = reload_check(service, mid).state.objects["object:map.1"]
    assert before.object_kind == "vine" and before.component["material"] == "wood"
    assert before.unattended == unattended
    assert not act(service, table, mid, mode, monkeypatch, NAME)
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.target_ids == (before.object_id,)]
    assert len(attacks) == 1 and attacks[0].payload["mode"] == "NORMAL"
    rolls = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and "axes_bark_cast" in r.reason]
    assert len(rolls) == 1 and len(rolls[0].dice) == 2
    assert rolls[0].total == sum(rolls[0].dice) + 2 + 4
    after = engine.state.objects[before.object_id]
    assert after.current_hp == before.current_hp - rolls[0].total
    assert after.object_kind == "vine" and after.component == before.component


def test_vine_preset_is_configurable_and_does_not_grant_bark_to_nonowners():
    from combat import object_rules

    stats = object_rules.stats({"kind": "vine"})
    assert (stats["name"], stats["material"], stats["size"], stats["ac"], stats["hp"]) == ("Vine", "wood", "small", 15, 3)
    assert object_rules.stats({"kind": "vine", "material": "rope", "hp": 30})["hp"] == 30
    engine = fight(build(AXES, [], axe=True, base=[CAST]), objects=[
        {"id": 1, "kind": "vine", "unattended": False, "x": 9, "y": 6}])
    assert "object:map.1" in engine.state.objects
    assert not candidates(engine, NAME)


@pytest.mark.parametrize("kind,material", [("wall_section", "stone"), ("crate", "wood"),
                                          ("custom", "wood"), ("pillar", "wood")])
def test_attended_objects_outside_explicit_shared_targets_stay_with_gm(kind, material):
    engine = fight(build(AXES, [BARK], axe=True, base=[CAST]), objects=[
        {"id": 1, "kind": kind, "material": material, "name": "Wooden barrier rope vine banner pole",
         "unattended": False, "blocks": False, "x": 9, "y": 6}])
    assert "object:map.1" in engine.state.objects  # No vacuous pass from a rejected map kind.
    assert not candidates(engine, NAME, "object:map.1")


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("natural", [1, 15, 20])
@pytest.mark.parametrize("unattended", [True, False])
def test_shock_bark_object_choice_commits_without_splinter_or_creature_effects(
        tmp_path, monkeypatch, mode, natural, unattended):
    original = DeterministicRollAuthority.d20
    def forced(self, **kwargs):
        roll = original(self, **kwargs)
        return roll.model_copy(update={"natural_result": natural, "total": natural + kwargs.get("modifier", 0),
                                       "dice": (natural,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", forced)
    service, table, mid = make_table(tmp_path, [BARK], AXES, mode, items=(AXE,), objects=[
        {"id": 1, "kind": "rope", "unattended": unattended, "x": 9, "y": 3, "hp": 999, "ac": 1}])
    end_until_hero(table, mid)
    before = reload_check(service, mid)
    hp = before.state.objects["object:map.1"].current_hp
    foe = PREFIX + "00000000"
    foe_before = before.state.actors[foe].model_dump(mode="json")
    assert not act(service, table, mid, mode, monkeypatch, SHOCK_NAME)
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.target_ids == ("object:map.1",)]
    assert len(attacks) == 1 and attacks[0].payload["mode"] == "NORMAL"
    rolls = [r for r in engine.rolls if r.reason.startswith("DAMAGE:") and "axes_bark_cast.shock" in r.reason]
    if natural == 1:
        assert not rolls and engine.state.objects["object:map.1"].current_hp == hp
    else:
        assert len(rolls) == 1 and len(rolls[0].dice) == (4 if natural == 20 else 2)
        assert rolls[0].total == sum(rolls[0].dice) + 2  # STR only; Splinter's PB is not part of Shock.
        assert engine.state.objects["object:map.1"].current_hp == hp - rolls[0].total
    assert engine.state.actors[foe].model_dump(mode="json") == foe_before
    assert not engine.state.actors[PREFIX + "aaaaaaaa"].action_available


def test_shock_bark_keeps_owner_possession_target_and_defense_gates():
    objects = [{"id": 1, "kind": "rope", "unattended": False, "x": 9, "y": 6, "hp": 999, "threshold": 999},
               {"id": 2, "kind": "crate", "unattended": False, "x": 10, "y": 6},
               {"id": 3, "kind": "rope", "x": 16, "y": 6}]
    assert not candidates(fight(build(AXES, [], axe=True, base=[CAST]), objects=objects), SHOCK_NAME)
    assert not candidates(fight(build(AXES, [BARK], axe=False, base=[CAST]), objects=objects), SHOCK_NAME)
    engine = fight(build(AXES, [BARK], axe=True, base=[CAST]), objects=objects)
    assert candidates(engine, SHOCK_NAME, "object:map.1")
    assert not candidates(engine, SHOCK_NAME, "object:map.2")
    assert not candidates(engine, SHOCK_NAME, "object:map.3")
    shock = next(a for a in engine.action_catalog.values() if a.display_name == SHOCK_NAME)
    splinter = next(a for a in engine.action_catalog.values() if a.display_name == NAME)
    assert shock.parameters["typed"]["object_weapon"]["damage"]["modifier"] == 2
    assert splinter.parameters["typed"]["object_weapon"]["damage"]["modifier"] == 6
    force_d20(engine, 15, 19)
    use(engine, SHOCK_NAME, "object:map.1")
    assert engine.state.objects["object:map.1"].current_hp == 999
    engine = fight(build(AXES, [BARK], axe=True, base=[CAST]), objects=objects)
    engine._apply_condition(engine.state.actors[shock.owner_id], "condition:typed.disarmed", "test", shock.owner_id,
                            expires_on="UNTIL_REMOVED", data={"disables_action": shock.parameters["typed"]["delivered_by"].split("#")[0]})
    assert not candidates(engine, SHOCK_NAME)
