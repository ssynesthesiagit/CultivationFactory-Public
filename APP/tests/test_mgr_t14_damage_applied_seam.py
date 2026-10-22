"""Post-packet damage_applied seam: ordering, inertness and True Reflection placement.

Synthetic Gate2Engine fixtures only (no model server, browser, or private publication).
Each test below fails on the pre-fix branch, where True Reflection listened on the
nested DAMAGE_COMMITTED event before Concentration/defeat processing.
"""
from combat import ext
from combat.ext import true_reflection
from tests.test_typed_executor import _reactor


def _commit(engine, target, attacker, amount):
    return engine._commit_damage(target, amount, "FIRE", "src.palm", attacker.entity_id, None, reaction_depth=0)


def test_damage_applied_runs_once_after_the_recorded_packet(monkeypatch):
    engine, attacker, target = _reactor("SEAM-ORDER", [])
    seen = []

    def probe(eng, event):
        seen.append((event, target.current_hp, [e.event_type for e in eng.events]))

    monkeypatch.setitem(ext._HOOKS, "damage_applied", [probe])
    hp_before = target.current_hp
    hp_damage = _commit(engine, target, attacker, 4)
    assert hp_damage > 0 and target.current_hp == hp_before - hp_damage
    assert len(seen) == 1
    event, hp_at_seam, types_at_seam = seen[0]
    assert event.event_type == "DAMAGE_COMMITTED" and event.payload["hp_damage"] == hp_damage
    assert hp_at_seam == target.current_hp  # the packet's HP was already applied
    assert types_at_seam[-1] == "DAMAGE_COMMITTED"  # nothing outside the packet ran first


def test_defeat_from_the_packet_settles_before_the_seam(monkeypatch):
    engine, attacker, target = _reactor("SEAM-DEFEAT", [])
    target.current_hp = 3
    seen = []

    def probe(eng, event):
        seen.append((target.current_hp, target.active, event.event_type))

    monkeypatch.setitem(ext._HOOKS, "damage_applied", [probe])
    _commit(engine, target, attacker, 20)
    assert seen == [(0, False, "DAMAGE_COMMITTED")]


def test_seam_is_inert_without_subscribers(monkeypatch):
    engine, attacker, target = _reactor("SEAM-INERT", [])
    monkeypatch.setitem(ext._HOOKS, "damage_applied", [])
    before = len(engine.events)
    hp_before = target.current_hp
    hp_damage = _commit(engine, target, attacker, 4)
    assert target.current_hp == hp_before - hp_damage
    assert [e.event_type for e in engine.events[before:]] == ["DAMAGE_COMMITTED"]


def test_true_reflection_trigger_listens_on_the_seam_not_the_nested_event():
    assert true_reflection.damage_trigger in ext.subscribers("damage_applied")
    assert true_reflection.damage_trigger not in ext.subscribers("event")
