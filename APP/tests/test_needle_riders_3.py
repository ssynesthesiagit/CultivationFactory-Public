"""Needle riders round 3 (NEEDLE1F11, NEEDLE1F13): regressions for the Arm Strike check scope.

Each test fails without its fix:

  Arm Strike, Strength/Dexterity checks  "-2 to weapon attacks and Strength/Dexterity checks" (limb-scoped). Before the fix the
                                         -2 reached only a grapple escape row; a plain Strength or Dexterity check the struck
                                         creature made at the table got nothing.
  Arm Strike, limb recorded at landing   the engine stores the limb when Arm Strike lands ("primary", its default striking limb).
"""

from types import SimpleNamespace
from contextlib import nullcontext

from combat import ext
from combat.ext import needle as N
from combat.typed_executor import Context, block_wall_breach
from tests.test_needle import _land_exploit


def _actor(limb="primary"):
    conditions = {"arm": SimpleNamespace(condition_id=N.PENALTY + "arm_strike", data={"limb": limb})}
    return SimpleNamespace(conditions=conditions, entity_id="foe")


def _check_bonus(actor, ability, typed=None):
    ctx = Context(engine=None, actor=actor, action=None, intent=None, typed=typed or {}, targets=[], target=None,
                  check_ability=ability)
    return sum(int(n) for n in ext.run("check_bonus", ctx, actor) if isinstance(n, int))


def test_arm_strike_gives_minus_two_to_a_dexterity_check():
    assert _check_bonus(_actor(), "DEX") == -2


def test_arm_strike_gives_minus_two_to_a_strength_check():
    assert _check_bonus(_actor(), "STR") == -2


def test_arm_strike_leaves_a_wisdom_check_alone():
    assert _check_bonus(_actor(), "WIS") == 0


def test_arm_strike_leaves_a_check_with_no_ability_named_alone():
    assert _check_bonus(_actor(), "") == 0


def test_arm_strike_gives_no_check_penalty_without_the_condition():
    assert _check_bonus(SimpleNamespace(conditions={}, entity_id="foe"), "DEX") == 0


def test_arm_strike_still_penalises_a_grapple_escape_row():
    typed = {"effects": [{"type": "escape_grapple"}]}
    assert _check_bonus(_actor(), "", typed) == -2


def test_pre_branch_arm_strike_without_a_limb_still_penalises_a_check():
    assert _check_bonus(SimpleNamespace(conditions={"arm": SimpleNamespace(condition_id=N.PENALTY + "arm_strike", data={})},
                                        entity_id="foe"), "STR") == -2


# NEEDLE1F13: the limb is recorded by the needle_condition effect from its row (default primary). No authority row names a
# secondary limb today, so this pins the row seam itself: a row that names "secondary" records it, and the STR/DEX check then leaves
# the primary-limb condition's penalty off. The test drives the real effect, not hand-built condition data.
def test_needle_condition_row_records_its_limb_and_a_secondary_limb_check_takes_no_penalty(monkeypatch):
    recorded = []
    monkeypatch.setattr(N, "timed_condition", lambda engine, actor, cid, source, src, expires, data: recorded.append((cid, data)))
    monkeypatch.setattr(ext, "run_strict", lambda *a, **k: [])
    monkeypatch.setattr(N, "_say", lambda *a, **k: None)
    foe = SimpleNamespace(active=True, entity_id="foe", display_name="Foe", conditions={})
    me = SimpleNamespace(entity_id="me", display_name="Me")
    ctx = SimpleNamespace(engine=None, source="src", actor=me, target=foe, targets=[foe])
    N.needle_condition(ctx, {"type": "needle_condition", "key": "arm_strike", "label": "Arm Strike", "limb": "secondary"})
    (cid, data), = recorded
    assert cid == N.PENALTY + "arm_strike" and data["limb"] == "secondary"
    foe.conditions = {"arm": SimpleNamespace(condition_id=cid, data=data)}
    assert _check_bonus(foe, "STR") == 0
    assert _check_bonus(foe, "DEX") == 0


def test_arm_strike_applied_by_the_engine_records_the_primary_limb_and_takes_the_check_penalty():
    engine, _me, foe = _land_exploit("TAL_FENCING_ARM_STRIKE")
    arm = next(c for c in foe.conditions.values() if c.condition_id == N.PENALTY + "arm_strike")
    assert (arm.data or {}).get("limb") == "primary"
    assert _check_bonus(foe, "STR") == -2


def test_arm_strike_penalizes_strength_wall_breach_check_on_real_resolver_path(monkeypatch):
    from combat import zones

    actor = _actor()
    zone = SimpleNamespace(trigger_profile={"wall": {"breach": {"ability": "STR", "skill": "Athletics"}},
                                            "numbers": {"save_dc": 10}, "name": "Dune Wall"})
    monkeypatch.setattr(zones, "breachable", lambda *args: (zone, (0, 0)))
    monkeypatch.setattr(zones, "breach", lambda *args: None)
    class Roll:
        total = 10
        def model_dump(self, **kwargs): return {"total": self.total}
    class Roller:
        def d20(self, **kwargs):
            observed.append(kwargs["modifier"])
            return Roll()
    observed = []
    engine = SimpleNamespace(d20_scope=lambda *args: nullcontext(), roller=Roller(),
                             _record_roll=lambda roll: None, _append_event=lambda *args, **kwargs: None)
    ctx = Context(engine, actor, None, None, {"numbers": {"check_bonus": 0}}, [], actor, {})
    block_wall_breach(ctx, {"result": ""})
    assert observed == [-2]
