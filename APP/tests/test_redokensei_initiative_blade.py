"""Kensei initiative/physical weapon and off-turn allowance regressions."""
from types import SimpleNamespace

from combat.canonical import canonical_sha256
from combat.ext import kensei
from combat.ext.hand_occupancy import weapon_grips
from tests import worker2_support as w
from tests.test_redokensei_severing import delivery, IRON, KENSEI
from tests.hunt12_support import hit_dice

SWORD = KENSEI + "sword_draws_before_thought"
BLADE = KENSEI + "blade_fist"
CHOICE = "choice:needle.sword_draws_before_thought"
HIT = "choice:needle.blade_fist"
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}


def setup(tmp_path, monkeypatch, *, features=(SWORD,), kit=None):
    def bundles(rows):
        delivery(rows)
        for row in rows:
            row["actor_template"]["initiative_bonus"] = 100 if row["actor_id"] == w.FOE else 0 if row["actor_id"] == w.OWNER else -100
            row.pop("bundle_sha256", None)
            row["bundle_sha256"] = canonical_sha256(row)
    # Leave the native setup candidate pending instead of advancing to OWNER.
    with monkeypatch.context() as patch:
        patch.setattr(w, "turn", lambda *args: None)
        return w.fixture(tmp_path, [], owner_features=[IRON, *features],
            owner_path="Body Refining", primary="Stamina", cl=18, owner_kit=kit,
            bundle_transform=bundles, positions={w.OWNER: {"x": 3, "y": 6},
            w.ALLY: {"x": 3, "y": 7}, w.FOE: {"x": 4, "y": 6}})


def finish(combat, table, mid, choice):
    engine = combat._load_session(mid).engine
    return w.settle(table, mid, engine.legal_candidates()[0].candidate_id,
                    choices={CHOICE: choice, "choice:needle.sword_draws_move": "first",
                    "choice:needle.kensei_weapon": "first", "choice:needle.sword_draws_target": "first",
                    "choice:needle.sword_draws_strike": "first"})


def test_initiative_ac_precedes_enemy_and_expires_at_first_owner_turn(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path, monkeypatch)
    initial = w.reload(tmp_path, mid)
    assert initial.state.setup_tasks
    assert all(a.turns_started == 0 for a in initial.state.actors.values())
    prompts = finish(combat, table, mid, "ac")
    options = next(p["choice"]["options"] for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert {o["id"] for o in options} == {"move", "strike", "ac", "advantage"}
    engine = w.reload(tmp_path, mid)
    assert engine.state.current_actor_id == w.FOE
    owner = engine.state.actors[w.OWNER]
    assert any(m.value == 2 and m.source_definition_id == SWORD for m in owner.modifiers.values())
    w.turn(table, mid, w.OWNER)
    engine = w.reload(tmp_path, mid)
    assert not any(m.source_definition_id == SWORD for m in engine.state.actors[w.OWNER].modifiers.values())
    assert not engine.state.setup_tasks


def test_first_round_advantage_survives_owner_turn_then_expires(tmp_path, monkeypatch):
    combat, table, mid = setup(tmp_path, monkeypatch)
    finish(combat, table, mid, "advantage")
    w.turn(table, mid, w.OWNER)
    w.settle(table, mid, table.state(mid)["menu"]["end_turn"], choices={})
    engine = w.reload(tmp_path, mid)
    assert engine.state.round_number == 1
    assert any(c.condition_id == kensei.FIRST_ATTACK for c in engine.state.actors[w.OWNER].conditions.values())
    for _ in range(4):
        if engine.state.round_number == 2:
            break
        w.settle(table, mid, table.state(mid)["menu"]["end_turn"], choices={})
        engine = w.reload(tmp_path, mid)
    assert engine.state.round_number == 2
    assert not any(c.condition_id == kensei.FIRST_ATTACK for c in engine.state.actors[w.OWNER].conditions.values())


def test_surprised_initiative_does_not_queue_a_later_choice():
    actor = SimpleNamespace(entity_id="owner", conditions={"surprise": SimpleNamespace(condition_id="condition:surprised")})
    engine = SimpleNamespace(typed_passive_rows={"owner": [{"kind": "sword_draws", "block": "kensei"}]},
                             state=SimpleNamespace(initiative_order=["owner"], actors={"owner": actor}))
    assert kensei.sword_draws_tasks(engine) == []


def test_blade_hit_stows_physical_weapon_and_cannot_repeat_on_same_turn(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = setup(tmp_path, monkeypatch, features=(BLADE,), kit=KIT)
    w.turn(table, mid, w.OWNER)
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    dao = next(key for key in owner.equipment_readiness if key.endswith(".weapon.dao"))
    assert owner.equipment_readiness[dao] == 1
    assert dao in weapon_grips(engine, owner)

    def hit():
        return w.settle(table, mid, w.candidate(combat, mid, "Measured hit", target=w.FOE).candidate_id,
            choices={HIT: "draw", "choice:needle.kensei_weapon": "first"})
    prompts = hit()
    assert any(p["context"]["reaction_source_id"] == HIT for p in prompts)
    engine = w.reload(tmp_path, mid)
    owner = engine.state.actors[w.OWNER]
    assert owner.equipment_readiness[dao] == 0
    assert dao not in weapon_grips(engine, owner)
    assert not any(p["context"]["reaction_source_id"] == HIT for p in hit())


def test_blade_hit_is_available_on_flowing_reaction_turn_after_reload(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = setup(tmp_path, monkeypatch, features=(BLADE, KENSEI + "flowing_blade_stance"))
    w.turn(table, mid, w.OWNER)
    w.settle(table, mid, w.candidate(combat, mid, "Flowing Blade Stance").candidate_id)
    w.settle(table, mid, w.candidate(combat, mid, "Measured hit", target=w.FOE).candidate_id, choices={HIT: "speed"})
    w.reload(tmp_path, mid)
    w.turn(table, mid, w.FOE)
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def rolls(self, **kw):
        while True:
            roll = original(self, **kw)
            if not (kw.get("actor_id") == w.FOE and str(kw.get("reason", "")).startswith("ATTACK")) or roll.natural_result == 1:
                return roll
    monkeypatch.setattr(DeterministicRollAuthority, "d20", rolls)
    prompts = w.settle(table, mid, w.candidate(combat, mid, "Unarmed Strike", target=w.OWNER).candidate_id,
        choices={HIT: "speed", "choice:needle.flowing_blade_answer": "first", "choice:needle.flowing_blade_step": None})
    assert any(p["context"]["reaction_source_id"] == HIT for p in prompts)
    engine = w.reload(tmp_path, mid)
    assert engine.state.actors[w.OWNER].turn_flags["blade_fist"] == kensei._stamp(engine)
    slows = [m for m in engine.state.actors[w.FOE].modifiers.values()
             if m.source_definition_id == BLADE and m.target_field == "speed_ft"]
    assert len(slows) == 1 and slows[0].value == -5
    assert slows[0].source_actor_id == w.OWNER


def test_initiative_advantage_applies_to_first_attack_and_is_consumed(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = setup(tmp_path, monkeypatch)
    finish(combat, table, mid, "advantage")
    w.turn(table, mid, w.OWNER)
    w.settle(table, mid, w.candidate(combat, mid, "Measured hit", target=w.FOE).candidate_id, choices={})
    engine = w.reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == w.OWNER)
    assert len(attack.payload["dice"]) == 2
    assert not any(c.condition_id == kensei.FIRST_ATTACK for c in engine.state.actors[w.OWNER].conditions.values())
