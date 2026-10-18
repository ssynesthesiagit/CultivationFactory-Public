"""Trigger normalization overlay (owner 2026-09-26): one shared canonical grammar for every reaction /
triggered feature's trigger, so combat can classify them reliably. This is a reversible overlay --
combat/trigger_overlay.py, consulted by combat/reaction_triggers.py's classify_mechanic -- built from
authority/typed_mechanics/trigger_normalization.jsonl (tools/normalize_triggers.py). It never edits the
rulebook sources, the catalog, or character creation.
"""
from __future__ import annotations

import hashlib
import json

from combat import trigger_overlay
from combat.reaction_triggers import classify_mechanic
from tools.trigger_grammar import EVENTS, validate


# ------------------------------------------------------------------ validator (tools/normalize_triggers.py)
def test_validate_accepts_a_clean_grounded_answer():
    result = {
        "normalized_trigger": "When a creature hits you with an attack within 10 feet with a melee attack",
        "event": "hit", "subject": "you", "range_ft": 10, "attack_filter": "melee",
        "condition": "", "mark_name": "", "extra_conditions": "", "intent_changed": False,
        "confidence": "high", "note": "",
    }
    checked, rejected = validate(result, "M1", "Iron Skin Ward", "A creature within 10 feet of you hits you with a melee attack")
    assert rejected == []
    assert checked["event"] == "hit"
    assert checked["range_ft"] == 10
    assert checked["attack_filter"] == "melee"


def test_validate_rejects_an_event_outside_the_canonical_list():
    result = {"normalized_trigger": "When you get mad", "event": "gets_angry", "confidence": "high"}
    checked, rejected = validate(result, "M2", "Made Up", "You get mad")
    assert checked["event"] == "other"
    assert any("event" in reason for reason in rejected)
    assert checked["confidence"] == "low"  # any rejection forces the row unusable


def test_validate_rejects_a_fabricated_range_not_printed_in_the_trigger():
    result = {"normalized_trigger": "When you take damage within 30 feet", "event": "damaged",
              "range_ft": 30, "confidence": "high"}
    checked, rejected = validate(result, "M3", "No Range Here", "You take damage")
    assert checked["range_ft"] is None
    assert any("range_ft" in reason for reason in rejected)


def test_validate_rejects_a_fabricated_mark_name_not_printed_in_the_trigger():
    result = {"normalized_trigger": "When a creature bearing your Storm Mark hits you", "event": "hit",
              "mark_name": "Storm Mark", "confidence": "high"}
    checked, rejected = validate(result, "M4", "No Mark Here", "A creature hits you with a melee attack")
    assert checked["mark_name"] == ""
    assert any("mark_name" in reason for reason in rejected)


def test_validate_requires_intent_changed_and_confidence_fields():
    result = {"normalized_trigger": "When you take damage", "event": "damaged"}  # no confidence/intent_changed
    checked, rejected = validate(result, "M5", "Bare", "You take damage")
    assert checked["confidence"] in ("high", "medium", "low")
    assert isinstance(checked["intent_changed"], bool)


def test_all_canonical_events_are_the_shared_seventeen():
    assert set(EVENTS) == {
        "attacked", "hit", "missed", "damaged", "drop_to_zero", "bloodied",
        "save_made", "save_failed", "save_succeeded", "condition_gained",
        "technique_targets", "technique_used", "critical_hit", "natural_1",
        "moved", "own_action", "other",
    }


# ------------------------------------------------------------------ overlay lookup (combat/trigger_overlay.py)
def _write_overlay(tmp_path, rows):
    path = tmp_path / "trigger_normalization.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def _row(mechanic_id, trigger, event, approved=True, **extra):
    return {
        "mechanic_id": mechanic_id, "text_sha256": hashlib.sha256(trigger.encode()).hexdigest(),
        "original_trigger": trigger, "event": event, "approved": approved, **extra,
    }


def test_overlay_lookup_matches_by_mechanic_id_and_current_trigger_hash(tmp_path, monkeypatch):
    trigger = "A creature bearing your Beauty Mark targets you with an attack"
    path = _write_overlay(tmp_path, [_row("BEAUTY_TEST", trigger, "attacked")])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    row = trigger_overlay.lookup("BEAUTY_TEST", trigger)
    assert row is not None and row["event"] == "attacked"


def test_overlay_lookup_is_none_when_the_trigger_text_changed(tmp_path, monkeypatch):
    original = "You take damage"
    path = _write_overlay(tmp_path, [_row("DMG_TEST", original, "damaged")])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    assert trigger_overlay.lookup("DMG_TEST", original) is not None
    assert trigger_overlay.lookup("DMG_TEST", "You take damage now") is None  # stale hash: old path


def test_overlay_lookup_ignores_unapproved_rows(tmp_path, monkeypatch):
    trigger = "You or an ally within 30 feet takes damage"
    path = _write_overlay(tmp_path, [_row("UNAPPROVED_TEST", trigger, "damaged", approved=False)])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    assert trigger_overlay.lookup("UNAPPROVED_TEST", trigger) is None


def test_kind_for_event_maps_saves_to_the_one_existing_save_kind():
    assert trigger_overlay.kind_for_event("save_made") == "save"
    assert trigger_overlay.kind_for_event("save_failed") == "save"
    assert trigger_overlay.kind_for_event("hit") == "hit"
    assert trigger_overlay.kind_for_event("other") == "unsupported"
    assert trigger_overlay.kind_for_event("nonsense") == "unsupported"
    assert trigger_overlay.kind_for_event("drop_to_zero") == "drop_to_zero"  # new kind, kept distinct for future wiring


# ------------------------------------------------------------------ classify_mechanic prefers the overlay
def test_classify_mechanic_uses_an_approved_overlay_row_over_the_old_classifier(tmp_path, monkeypatch):
    # The old free-text classifier cannot recognize this odd phrasing at all (would be "unsupported"),
    # but the overlay says it is a clean "damaged" trigger.
    trigger = "You would suffer harm from a hostile source"
    path = _write_overlay(tmp_path, [_row("ODD_WORDING_TEST", trigger, "damaged")])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    mechanic = {"mechanic_id": "ODD_WORDING_TEST", "activation": {"economy": "reaction", "trigger": trigger}}
    match = classify_mechanic(mechanic)
    assert match.kind == "damaged"
    assert match.runnable


def test_classify_mechanic_falls_back_when_the_overlay_row_is_unapproved(tmp_path, monkeypatch):
    trigger = "A creature hits you with a melee attack"  # the old classifier already handles this cleanly
    path = _write_overlay(tmp_path, [_row("FALLBACK_TEST", trigger, "other", approved=False)])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    mechanic = {"mechanic_id": "FALLBACK_TEST", "activation": {"economy": "reaction", "trigger": trigger}}
    match = classify_mechanic(mechanic)
    assert match.kind == "hit"  # old free-text path, not the unapproved overlay row's "other"


def test_classify_mechanic_falls_back_when_no_overlay_row_exists(tmp_path, monkeypatch):
    path = _write_overlay(tmp_path, [])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    mechanic = {"mechanic_id": "NEVER_NORMALIZED", "activation": {"economy": "reaction", "trigger": "You fail a saving throw."}}
    match = classify_mechanic(mechanic)
    assert match.kind == "save"


def test_classify_mechanic_still_reports_filters_from_the_original_text(tmp_path, monkeypatch):
    # The minimal edit only overrides "kind"; melee/ranged/range/sight filters still come from the
    # original free-text parse (classify_trigger), whether or not the overlay fires.
    trigger = "A creature within 30 feet hits you with a ranged attack"
    path = _write_overlay(tmp_path, [_row("FILTERS_TEST", trigger, "hit")])
    monkeypatch.setattr(trigger_overlay, "OVERLAY_PATH", path)
    trigger_overlay._CACHE.clear()
    mechanic = {"mechanic_id": "FILTERS_TEST", "activation": {"economy": "reaction", "trigger": trigger}}
    match = classify_mechanic(mechanic)
    assert match.kind == "hit"
    assert match.range_ft == 30
    assert match.ranged_only is True


def test_rewrites_that_would_break_a_mechanic_are_not_used():
    """Owner 2026-09-26: "double check the trigger normalization to make sure the mechanics aren't damaged"."""
    from combat.trigger_overlay import enforceable, own_action, usable

    base = {"model": "deepseek/deepseek-v4.1-flash via commandcode", "confidence": "high", "event": "hit", "condition": "", "extra_conditions": ""}
    # "After you hit ..." is the reactor's own hit, not an attack on the reactor.
    assert own_action({**base, "normalized_trigger": "When you hit a hostile creature"}) and not usable({**base, "normalized_trigger": "When you hit a hostile creature"})
    # A limit combat can't check would make the reaction fire more often than its rule allows.
    # Owner 2026-09-26: a damage type is no longer such a limit for a "damaged" row -- typed_reactions.py's
    # on_damage family now reads the incoming type off the row's damage_types.
    assert enforceable({**base, "event": "damaged", "normalized_trigger": "When you take Fire damage"})
    assert not enforceable({**base, "event": "hit", "normalized_trigger": "When a creature hits you with Fire damage"})
    assert not enforceable({**base, "event": "damaged", "normalized_trigger": "When you take damage", "extra_conditions": "Fire damage dealt by a hostile creature"})
    assert not enforceable({**base, "event": "damaged", "normalized_trigger": "When you take damage from a creature inside your Spear Line"})
    # Sight, reach, timing and extra "or" alternatives (which only narrow it) are fine.
    assert enforceable({**base, "event": "missed", "normalized_trigger": "When a creature within your reach misses you with a melee attack"})
    assert enforceable({**base, "event": "damaged", "normalized_trigger": "When you take damage", "extra_conditions": "you can perceive; after damage is rolled and before it is applied; or an ally takes damage"})
