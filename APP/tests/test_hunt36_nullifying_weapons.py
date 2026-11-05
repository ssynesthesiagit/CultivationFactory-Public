"""Printed Nullifying Strike: 'Void Needle, an unarmed strike, or a melee weapon attack'; '2 CP or 2 Stamina'."""
import hashlib
import pytest
from tests.hunt36_support import LEFT, RIGHT, fight, reload, send, turn
from tests.test_hunt12_critical import KIT as TREASURE

NULL = "TAL_VOID_NULLIFYING_STRIKE"


def seed_for(kind, critical):
    for i in range(10000):
        seed = f"H36-nullifying-{kind}-{'crit' if critical else 'normal'}-{i}"
        natural = int.from_bytes(hashlib.sha256(seed.encode() + b"\0" + (2).to_bytes(16, "big")).digest(), "big") % 20 + 1
        if natural == (20 if critical else 19):
            return seed
    raise AssertionError("no natural seed")


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("critical", [False, True])
@pytest.mark.parametrize("kind", ["melee", "treasure"])
def test_nullifying_melee_hit_and_critical_commit_reload(tmp_path, kind, critical, ai):
    combat, table, mid = fight(tmp_path, [NULL], primary="Stamina", kit=TREASURE if kind == "treasure" else None, seed=seed_for(kind, critical))
    turn(combat, table, mid)
    engine = reload(combat, mid)
    before = engine.state.event_sequence
    stamina = engine.state.actors[LEFT].resources["resource:core.stamina"]
    label = "Mountainblade attack" if kind == "treasure" else "Bi Shou (Dagger) attack"
    candidate = next(c for c in engine.legal_candidates() if c.display_name == label and tuple(c.target_ids) == (RIGHT,))
    prompts = send(combat, table, mid, candidate.candidate_id, ai=ai, pick=lambda o: "Speed -10" in o["label"])
    if not ai:
        assert any(p.get("choice") for p in prompts), "Manual owner chooses after the triggering hit"
    engine = reload(combat, mid)
    events = [e for e in engine.events if e.sequence > before]
    attack = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert attack.payload["provisional_hit"] and (attack.payload["natural_result"] == 20) == critical
    bonus = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"]
    assert len(bonus) == 1 and bonus[0].payload["expression"] == ("6d6+0" if critical else "3d6+0")
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == stamina - 2


def test_nullifying_does_not_augment_thrown_or_ranged_weapons(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL], primary="Stamina")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    assert not [a for a in engine.action_catalog.values() if "Nullifying Strike" in a.display_name and (a.parameters.get("typed") or {}).get("weapon") and (a.parameters.get("typed") or {}).get("range_ft")]
    assert not [a for a in engine.action_catalog.values() if (a.parameters.get("typed") or {}).get("range_ft")
                and (a.parameters.get("typed") or {}).get("paid_hit_choices")]


def test_melee_target_seam_accepts_two_independent_reviewed_modifiers():
    """Delivery targeting is generic, not a Nullifying Strike special case."""
    import copy
    from combat.factory_compiler import _core_modifier_pass, compile_character
    from combat.gate2_runtime_models import ActionDefinition
    from tests.h1_support import mechanics, sheet

    bundle = compile_character(sheet([], kit={"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1},
        {"item_id": "tianxia.mortal.weapon.gong_jian", "quantity": 1}]}}), actor_id=LEFT)
    actions = [ActionDefinition.model_validate(a) for a in bundle["action_catalog"]]
    mods = {}
    for key in ("test:first", "test:second"):
        row = copy.deepcopy(mechanics()[NULL])
        row.update(name=key, modifier={"targets": ["Melee weapon attack"], "scope": "named", "when": "hit",
                                     "effects": [{"type": "extra_damage", "flat": 1, "applies_to": "target"}]})
        mods[key] = row
    changed, rows = _core_modifier_pass(actions, list(mods), mods, "Qi", ["Qi"], automated=set(),
                                       foundation_resource=None, actor_id=LEFT, numbers={"cl": 15, "pb": 4})
    assert {r["id"] for r in rows if r["status"] == "applied"} == set(mods)
    for action, original in zip(changed, actions):
        typed = action.parameters.get("typed") or {}
        if typed.get("weapon") and not typed.get("range_ft") and any(e.get("attack_kind") == "weapon" for e in typed.get("effects") or []):
            assert {e["source_modifier"] for attack in typed["effects"] for e in attack.get("on_hit") or [] if e.get("source_modifier")} == set(mods)
        else:
            assert action == original


def test_paid_hit_contract_is_generic_and_preserves_ordinary_attack_counts():
    import copy
    from combat.factory_compiler import _core_modifier_pass, compile_character
    from combat.gate2_runtime_models import ActionDefinition
    from tests.h1_support import mechanics, sheet

    bundle = compile_character(sheet(["tianxia.path.body_refining.feature.extra_attack"], kit={"starting_kit": {
        "items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 2}]}}), actor_id=LEFT)
    actions = [ActionDefinition.model_validate(a) for a in bundle["action_catalog"]]
    mods = {}
    for key in ("test:first", "test:second"):
        row = copy.deepcopy(mechanics()[NULL])
        row.update(name=key, modifier={"targets": ["Melee weapon attack"], "scope": "named", "when": "hit",
            "optional": True, "extra_cp": 2, "effects": [{"type": "extra_damage", "flat": 1, "applies_to": "target"}]})
        mods[key] = row
    changed, _ = _core_modifier_pass(actions, list(mods), mods, "qi", {"qi": 30}, automated=set(),
        foundation_resource=None, actor_id=LEFT, numbers={"cl": 10, "pb": 4})
    assert len(changed) == len(actions), "Paid hit riders do not duplicate the Attack action"
    for action, original in zip(changed, actions):
        assert action.parameters.get("expected_damage") == original.parameters.get("expected_damage")
        typed = action.parameters.get("typed") or {}
        if typed.get("paid_hit_choices"):
            assert {c["id"] for c in typed["paid_hit_choices"]} == set(mods)
            assert action.costs == original.costs and action.economy == original.economy
            assert typed["effects"] == original.parameters["typed"]["effects"]
            assert all(c["options"][0]["costs"] == [["resource:core.qi", 2]] for c in typed["paid_hit_choices"])
        else:
            assert action == original
