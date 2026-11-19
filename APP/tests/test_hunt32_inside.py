"""Continuous outside-zone effects stop and resume across real prison transactions.

The sealed scratch zone carries the printed Numbing Darkness row and a synthetic
modifier to exercise the shared lifecycle, without testing Darkness's activation.
"""
import pytest

from combat import zones
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_hunt32_edge import FOE, OWNER, act, match, reload
from tests.test_hunt32_prison import ALLY, PRISON


def inside_setup():
    bundle = compile_character(sheet(["DARK_BASE_DARKNESS", "TAL_DARK_NUMBING_DARKNESS"], cl=20), actor_id=OWNER)
    spec = next(a["parameters"]["typed"]["zone_spec"] for a in bundle["action_catalog"]
                if a["display_name"] == "Darkness")
    row = spec["shapes"]["TAL_DARK_NUMBING_DARKNESS"]["inside"][0]
    row = {**row, "modifiers": [{"field": "armor_class", "value": 7}]}
    return [
        {"name": "Setup outside area", "effects": [{"type": "zone"}],
         "typed": {"zone_spec": {"name": "Scratch continuous area", "shape": "sphere", "size_ft": 15,
                                 "centered_on_self": True, "duration": {"kind": "scene"}, "inside": [row]}}},
        {"name": "Setup carried condition", "target": "HOSTILE_ENTITY", "effects": [
            {"type": "condition", "condition": "burning", "applies_to": "target", "expires_on": "UNTIL_REMOVED"}]},
        {"name": "Break prison concentration", "effects": [
            {"type": "damage", "flat": 59, "damage_type": "force", "applies_to": "self"}]},
        {"name": "Setup unrelated incapacitation", "target": "HOSTILE_ENTITY", "effects": [
            {"type": "condition", "condition": "incapacitated", "applies_to": "target", "expires_on": "UNTIL_REMOVED"}]},
    ]


def assert_inside(engine, expected):
    victim = engine.state.actors[FOE]
    rows = [c for c in victim.conditions.values() if c.condition_id == zones.ZONE_EFFECT]
    assert len(rows) == int(expected)
    mids = [m.modifier_id for m in victim.modifiers.values() if m.applies_to == "WHILE_INSIDE_ZONE"]
    assert len(mids) == int(expected)
    if expected:
        assert rows[0].data["rule"]["save_mode"]["CON"] == "DISADVANTAGE"
        assert rows[0].data["zone_modifiers"] == mids


@pytest.mark.parametrize("release,mode", [("expiry", "MANUAL"), ("expiry", "LOCAL_AUTO"),
                                         ("concentration", "MANUAL")])
def test_inside_zone_removed_during_prison_restored_on_release(tmp_path, mode, release):
    combat, table, mid = match(tmp_path, [PRISON], allies=True, ally_mode=mode, ally_mids=[],
                               setup_actions=inside_setup())
    assert act(table, mid, "Setup outside area")["status"] == "COMMITTED"
    assert act(table, mid, "Setup carried condition", FOE)["status"] == "COMMITTED"
    before = reload(combat, tmp_path, mid)
    assert_inside(before, True)
    carried = {c.instance_id for c in before.state.actors[FOE].conditions.values()
               if c.condition_id == "condition:typed.burning"}
    assert carried
    assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    held = reload(combat, tmp_path, mid)
    assert any(c.condition_id == "condition:typed.incapacitated" for c in held.state.actors[FOE].conditions.values())
    assert_inside(held, False)
    assert carried <= set(held.state.actors[FOE].conditions)
    # Creating another outside area during isolation must not reapply its effects.
    assert act(table, mid, "Setup outside area")["status"] == "COMMITTED"
    assert_inside(reload(combat, tmp_path, mid), False)
    if release == "concentration":
        # Scratch self-damage leaves the caster alive and forces the native
        # concentration check to fail; starting another technique would not end
        # Fold Prison because this engine supports multiple concentrations.
        assert act(table, mid, "Break prison concentration")["status"] == "COMMITTED"
    else:
        assert act(table, mid)["status"] == "COMMITTED"
        if mode == "MANUAL":
            assert act(table, mid)["status"] == "COMMITTED"
        else:
            for _ in range(12):
                assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
                assert_inside(reload(combat, tmp_path, mid), False)
                if table.state(mid)["menu"]["actor_id"] != ALLY:
                    break
        assert table.state(mid)["menu"]["actor_id"] == FOE
        assert act(table, mid)["status"] == "COMMITTED"
    after = reload(combat, tmp_path, mid)
    if release == "concentration":
        assert after.state.actors[OWNER].active
        assert any(e.event_type == "CONCENTRATION_ENDED" and e.payload.get("reason") == "FAILED_DAMAGE_CHECK"
                   for e in after.events)
    assert not any(c.condition_id == "condition:typed.incapacitated" for c in after.state.actors[FOE].conditions.values())
    assert_inside(after, True)  # newest overlapping copy only, no duplicate stacking
    assert carried <= set(after.state.actors[FOE].conditions)


def test_unrelated_incapacitation_keeps_continuous_zone_effects(tmp_path):
    combat, table, mid = match(tmp_path, [], setup_actions=inside_setup())
    assert act(table, mid, "Setup outside area")["status"] == "COMMITTED"
    before = reload(combat, tmp_path, mid)
    assert act(table, mid, "Setup unrelated incapacitation", FOE)["status"] == "COMMITTED"
    after = reload(combat, tmp_path, mid)
    assert_inside(after, True)
    assert [c.model_dump() for c in after.state.actors[FOE].conditions.values() if c.condition_id == zones.ZONE_EFFECT] == [
        c.model_dump() for c in before.state.actors[FOE].conditions.values() if c.condition_id == zones.ZONE_EFFECT]


@pytest.mark.parametrize("holder", [OWNER, FOE])
def test_inside_owner_and_overlapping_prison_lifecycle(tmp_path, holder):
    """Supplementary engine lifecycle coverage, not extra table transactions."""
    combat, table, mid = match(tmp_path, [PRISON], setup_actions=inside_setup())
    assert act(table, mid, "Setup outside area")["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if (a.parameters.get("typed") or {}).get("source") == PRISON)
    actor = engine.state.actors[holder]
    for _ in range(2):
        engine._apply_condition(actor, "condition:typed.incapacitated", source, OWNER, expires_on="UNTIL_REMOVED")
    assert_inside(engine, False)
    prisons = [c for c in actor.conditions.values() if c.source_definition_id == source]
    for index, condition in enumerate(prisons):
        actor.conditions.pop(condition.instance_id)
        # A remover's source differs from the prison: original-instance
        # attribution must still reconcile, including while another copy holds.
        engine._append_event("CONDITION_REMOVED", "test:dispel", actor_id=OWNER, target_ids=(holder,),
                             payload={"instance_id": condition.instance_id, "condition_id": condition.condition_id})
        assert_inside(engine, index == 1)
