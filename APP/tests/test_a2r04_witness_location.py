"""Witness knows location without sight, through committed actions and cold reload."""
from types import SimpleNamespace

import pytest

from combat import senses, stealth, target_knowledge, zones
from combat.ext import smoke_veil
from combat.typed_executor import bears_mark, mark_condition_id
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn
from tests.test_a2r04_smoke_sound import _resonance_on_hold
from tests.test_a2r04_mirror_contract import hold

WITNESS = "TAL_SMOKE_SOOT_MARKED_WITNESS"
VEIL, DENSE = "SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_DENSE_VEIL"
# Explicit dynamic compiler input for the public-CI dependency closure.
SMOKE_FEATURE_BLOCKS = "combat/rules/feature_blocks.d/auto43_smoke.json"


def test_witness_native_bonus_then_other_owners_dense_veil_preserves_unseen_penalty(tmp_path, monkeypatch):
    _, table, mid = fixture(tmp_path, [WITNESS, "SMOKE_BASE_SMOKE_TRACE", "SMOKE_BASE_SMOKE_RESPONSES"],
                            foe_sheet=sheet([VEIL, DENSE]), foe_position={"x": 3, "y": 5}, seed="WITNESS-LOCATION")

    def trace(engine):
        engine._apply_condition(engine.state.actors[FOE], mark_condition_id("Smoke Trace", OWNER),
                                "test:trace", OWNER, expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(trace)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    action = next(c for c in engine.legal_candidates() if c.display_name == "Soot-Marked Witness")
    settle(table, mid, action.candidate_id)
    assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Smoke Trace")
    turn(table, mid, FOE)
    # Service menus offer an unbound square picker; the exhaustive engine
    # query instead starts with a concrete square elsewhere on the map.
    action = next(option for group in table.state(mid)["menu"]["actions"]
                  for option in group["options"] if "Smoke Veil" in option["label"])
    settle(table, mid, action["candidate_id"],
           picks={"choice:placement_menu.square": "cell:3,5,0"})

    def hide(engine):
        # Stage a successful native Hide inside a committed Hold, after the
        # caster's Action made its screen. No hand-written hidden mask/state.
        assert stealth.hide(engine, engine.state.actors[FOE], 50, "test:hide")

    _resonance_on_hold(monkeypatch)(hide)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    owner, observer, foe = (engine.state.actors[x] for x in (OWNER, ALLY, FOE))
    veil = next(z for z in zones.typed_zones(engine) if z.owner_id == FOE)
    assert veil.trigger_profile["obscured"] == "heavy"
    assert senses.pinpoints(engine, owner, foe)
    assert target_knowledge.located(engine, owner, foe)
    assert stealth.hidden(foe) in senses.plugin_condition_masks(engine, owner, foe)[FOE]
    assert not senses.perceives(engine, owner, foe)
    assert not senses.perceives(engine, owner, foe, sight_only=True)
    assert not target_knowledge.can_see(engine, owner, foe)
    assert not zones.obscurement_ignored(engine, veil, owner, foe)
    assert "DISADVANTAGE" in zones.attack_modes(engine, owner, foe)
    assert engine._attack_mode(owner, foe) == "DISADVANTAGE"
    assert not senses.pinpoints(engine, observer, foe)
    assert not target_knowledge.located(engine, observer, foe)
    assert not senses.plugin_condition_masks(engine, observer, foe).get(FOE)
    assert not senses.perceives(engine, observer, foe)
    # Unseen attacker benefits are preserved too: knowing location is not sight.
    assert "ADVANTAGE" in zones.attack_modes(engine, foe, owner)
    assert engine._attack_mode(foe, owner) == "ADVANTAGE"
    turn(table, mid, OWNER)
    assert not senses.pinpoints((engine := reload(tmp_path, mid)), engine.state.actors[OWNER], engine.state.actors[FOE])


@pytest.mark.parametrize("cause", ["range", "invisible", "independent_hide", "unknown_hide"])
def test_witness_location_does_not_defeat_other_hiding_causes(tmp_path, monkeypatch, cause):
    _, table, mid = fixture(tmp_path, [VEIL, DENSE, WITNESS], foe_position={"x": 3, "y": 5}, seed="WITNESS-BOUNDARY")

    def trigger(engine):
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        smoke_veil.witness_reveal(SimpleNamespace(engine=engine, actor=owner, target=foe, source="test:witness"), {})
        if cause == "range":
            next(c for c in foe.conditions.values() if c.condition_id == smoke_veil.REVEALED).data["range_ft"] = 1
        elif cause == "invisible":
            engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
        else:
            engine._apply_condition(foe, stealth.HIDDEN, "test:hide", FOE, expires_on="UNTIL_REMOVED",
                                    data={"stealth_total": 50, **({"hiding_basis": "sound_reliance"} if cause == "independent_hide" else {})})
    _resonance_on_hold(monkeypatch)(trigger)
    hold(table, mid, tmp_path)
    engine = reload(tmp_path, mid)
    assert not senses.pinpoints(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
