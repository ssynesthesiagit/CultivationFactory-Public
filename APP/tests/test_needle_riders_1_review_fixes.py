"""needle-riders-1 review fixes (NEEDLE1RB1): one regression per finding, each failing on the pre-fix code.

  F1  a reachable-but-blocked object burns the Focus and the once-per-fight use   -> reach is tested before anything is paid
  F2  spend_focus's False return is discarded                                      -> a refused Focus stops the attack
  F3  the Arm Strike rider under-describes the engine's STR/DEX checks            -> rider names them
  F4  the object branch passes the literal "weapon" as the attack kind            -> passes the object weapon group
  F5  the object row declares a spend_resource that never runs                    -> Focus is paid exactly once
  F6  the inheritance's own Speed movement is recorded as a Reaction              -> recorded as an Action move
  F7  a pre-branch Arm Strike condition (no limb) narrows mid-fight               -> keeps its all-attacks penalty
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from combat.ext import needle
from combat.gate5_service import CombatService
from tests import r1i_service_support as R
from tests.test_carry import KIT
from tests.test_needle_riders_1 import _crate

APP = Path(__file__).resolve().parents[1]
ROOT = APP  # the CombatService source root is APP/ (static/, combat/ live there)
OPENING = "Bi Shou (Dagger) attack: The One Opening Beneath Heaven (at an object)"


def _fight(tmp_path, seed, arena_edit=_crate):
    return R.fixture(tmp_path, ["TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN", "TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"],
                     seed=seed, owner_kit={"starting_kit": KIT}, owner_dc=50, foe_ac=1, foe_score=6, arena_edit=arena_edit)


def _object_attacks(engine):
    return [r for r in engine.rolls if str(r.reason).startswith("ATTACK:") and "#one_opening_object" in str(r.reason)]


def _focus_spends(engine):
    return [e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == needle.FOCUS
            and "one_opening" in str(e.source_id)]


def _far_crate(arena):
    # 25 ft from the owner's start (3,6): beyond the 5 ft normal reach, inside Speed plus reach, so the candidate is offered.
    arena["map_objects"] = [{"id": 1, "kind": "crate", "x": 8, "y": 5, "hp": 999, "ac": 1, "unattended": True}]


def test_f1_a_blocked_inheritance_spends_no_focus_and_keeps_the_once_per_fight_use(tmp_path, monkeypatch):
    from combat import typed_executor
    monkeypatch.setattr(typed_executor, "block_reaction_move", lambda *a, **k: None)  # a wall stops the movement short
    combat, table, mid, _send, commit = _fight(tmp_path, "NEEDLE1RB1-F1", _far_crate)
    try:
        commit(R.candidate(table, mid, OPENING, "object:map.1"))
    except Exception:
        pass  # a refused commit spends nothing either
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert not _object_attacks(engine)
    assert not _focus_spends(engine), "Focus was paid for an object the inheritance could not reach"


def test_f5_a_landed_object_attack_pays_exactly_one_martial_focus(tmp_path):
    combat, table, mid, _send, commit = _fight(tmp_path, "NEEDLE1RB1-F5")
    commit(R.candidate(table, mid, OPENING, "object:map.1"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert _object_attacks(engine), "the object attack did not resolve"
    assert len(_focus_spends(engine)) == 1, [e.payload for e in _focus_spends(engine)]


def test_f2_a_refused_focus_spend_stops_the_object_attack(tmp_path, monkeypatch):
    monkeypatch.setattr(needle, "spend_focus", lambda *a, **k: False)
    combat, table, mid, _send, commit = _fight(tmp_path, "NEEDLE1RB1-F2")
    try:
        commit(R.candidate(table, mid, OPENING, "object:map.1"))
    except Exception:
        pass
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert not _object_attacks(engine), "the attack resolved although the Focus spend was refused"


def test_f4_the_object_branch_passes_the_object_weapon_group_as_attack_kind(tmp_path, monkeypatch):
    # The ordinary object attack keys its damage bonus and object_hit by the weapon group (objects.attack_group). Force the group to
    # "axe" at compile time: the One Opening's object branch must pass that same key, not the literal "weapon".
    from combat.ext import objects, run_strict as _rs
    import combat.ext as ext
    monkeypatch.setattr(objects, "attack_group", lambda row, typed, attack: "axe")
    kinds = []
    real_bonus = objects.object_attack_damage_bonus
    monkeypatch.setattr(objects, "object_attack_damage_bonus",
                        lambda ctx, obj, kind, dice: kinds.append(("bonus", kind)) or real_bonus(ctx, obj, kind, dice))
    real_strict = ext.run_strict
    monkeypatch.setattr(ext, "run_strict", lambda name, ctx, obj, kind, *a, **k: kinds.append((name, kind)) or real_strict(name, ctx, obj, kind, *a, **k))
    combat, table, mid, _send, commit = _fight(tmp_path, "NEEDLE1RB1-F4")
    commit(R.candidate(table, mid, OPENING, "object:map.1"))
    assert ("bonus", "axe") in kinds, kinds
    assert ("object_hit", "axe") in kinds, kinds


def test_f6_the_inheritance_speed_move_is_an_action_not_a_reaction(tmp_path):
    combat, table, mid, _send, commit = _fight(tmp_path, "NEEDLE1RB1-F6", _far_crate)
    commit(R.candidate(table, mid, OPENING, "object:map.1"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and "one_opening" in str(e.source_id)]
    assert moves, "the inheritance should move toward the object in this fixture"
    assert all(e.payload.get("reaction") is False for e in moves), [e.payload.get("reaction") for e in moves]


def test_f8_the_object_branch_uses_only_public_objects_helpers():
    # ARCH guard (test_private_plugin_dependencies): needle_opening must not import objects' private helpers; objects exports attack_group.
    import ast
    from combat.ext import objects
    tree = ast.parse((APP / "combat/ext/needle_opening.py").read_text(encoding="utf-8"))
    private = [a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "objects" for a in n.names if a.name.startswith("_")]
    assert private == [], private
    assert callable(objects.attack_group) and not hasattr(objects, "_group")


def test_f3_the_arm_strike_rider_names_the_strength_and_dexterity_checks():
    text = json.dumps(json.loads((APP / "authority/typed_mechanics/reviewed_final.d/martial.json").read_text()))
    assert "Strength and Dexterity checks that rely on that limb" in text


def test_f7_a_pre_branch_arm_strike_without_a_limb_keeps_its_penalty_on_every_attack(monkeypatch):
    off_hand = SimpleNamespace(typed={"weapon": {"limb": "off"}})
    monkeypatch.setattr(needle, "condition", lambda actor, key: SimpleNamespace(data={}) if key == needle.PENALTY + "arm_strike" else None)
    assert needle._attack_penalty(off_hand, object()) == -2  # saved before the limb was recorded: no narrowing mid-fight
    monkeypatch.setattr(needle, "condition", lambda actor, key: SimpleNamespace(data={"limb": "primary"}) if key == needle.PENALTY + "arm_strike" else None)
    assert needle._attack_penalty(off_hand, object()) is None  # a recorded limb still scopes the penalty
