"""Post-packet damage_applied seam: ordering, inertness and True Reflection placement.

Synthetic Gate2Engine fixtures only (no model server, browser, or private publication).
Each test below fails on the pre-fix branch, where True Reflection listened on the
nested DAMAGE_COMMITTED event before Concentration/defeat processing.
"""
from types import SimpleNamespace

import pytest

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
    new_types = [e.event_type for e in engine.events[before:]]
    # The seam with no subscribers adds no event of its own: no reaction, match or GM event.
    assert "DAMAGE_COMMITTED" in new_types
    assert not {"MATCH_ENDED", "GM_RIDER", "REACTION_OPENED"} & set(new_types)


def test_true_reflection_trigger_listens_on_the_seam_not_the_nested_event():
    assert true_reflection.damage_trigger in ext.subscribers("damage_applied")
    assert true_reflection.damage_trigger not in ext.subscribers("event")


def test_concentration_lost_to_the_packet_is_resolved_before_the_seam(monkeypatch):
    """Review 151748: a lethal or concentration-breaking packet must settle Concentration first."""
    engine, attacker, target = _reactor("SEAM-CONC", [])
    engine._start_concentration(target, "spell.held")
    assert target.concentration is not None
    seen = []

    def lose_concentration(actor, *args, **kwargs):
        actor.concentration = None  # the save failed: Concentration ends

    def probe(eng, event):
        seen.append(target.concentration)

    monkeypatch.setattr(engine, "_concentration_check", lose_concentration)
    monkeypatch.setitem(ext._HOOKS, "damage_applied", [probe])
    _commit(engine, target, attacker, 4)
    assert seen == [None]  # the seam saw the settled state, not the held Concentration


def test_no_reaction_opens_once_the_match_has_ended(monkeypatch):
    """Review 143522 (optional): the seam must not open a reaction after the fight has ended."""
    calls = []
    monkeypatch.setattr(true_reflection, "_manifest", lambda *a, **k: calls.append(a), raising=False)
    engine = SimpleNamespace(state=SimpleNamespace(terminal_result=object()))  # match already decided
    event = SimpleNamespace(payload={"hp_damage": 4}, actor_id="a", target_ids=("t",), source_definition_id="src.palm")
    true_reflection.damage_trigger(engine, event)
    assert calls == []


def test_summon_rejects_an_origin_without_a_destination():
    """Review 143522 (optional): placement_origin with no destination would be silently ignored."""
    from combat import summons
    from combat.gate2_runtime_models import Position
    engine, _, target = _reactor("SUMMON-ORIGIN", [])
    with pytest.raises(ValueError, match="requires a destination"):
        summons.summon(engine, target, "true_doppelganger", SRC_SUMMON, placement_origin=Position(x=0, y=0, z=0), placement_range_ft=10)


SRC_SUMMON = "tianxia.subpath.qi.mirror_cultivator.feature.true_reflection"
