"""Regression tests for the Sol review findings on Quarantine Ward (fix round RB1).

Each test fails on the pre-fix code: an AI maker's raise selected enemies, its own outward token was refused,
a vetoed token was logged as gained, overlapping Wards asked identical words, and the ward fight never
checked replay or verify.
"""
from __future__ import annotations

from combat.ext import disease, rider_choices
from tests.test_disease_quarantine_ward import (
    OUTSIDE, OWNER, SELECTED, _fight, _fresh, _raise_ward,
)

SOURCE = "test:ward_review_spread"


def _ward_profile(engine):
    zones = disease._ward_zones(engine)
    assert len(zones) == 1
    return zones[0].trigger_profile[disease.QUARANTINE_WARD_STATE]


def test_ai_maker_raise_offers_only_its_own_side_for_protection(tmp_path, monkeypatch):
    """Finding: an AI maker's raise-time answer selected every creature in the veil, enemies included.

    The raise must hand the automatic chooser only the maker and its allies, and the saved ward must not protect
    an enemy the maker never meant to shield."""
    combat, table, mid = _fight(tmp_path)
    real_pick = rider_choices.pick
    seen = []

    def spy(engine, owner, key, name, options, **kwargs):
        if key == "quarantine_ward_recipients":
            seen.append(kwargs)
        return real_pick(engine, owner, key, name, options, **kwargs)

    monkeypatch.setattr(rider_choices, "pick", spy)
    _raise_ward(combat, table, mid)
    assert seen, "the raise never asked who the ward protects"
    automatic = seen[0].get("automatic_options")
    assert automatic is not None and SELECTED not in automatic
    assert OWNER in automatic
    assert SELECTED not in (seen[0].get("preferred") or [])


def test_ai_maker_spreads_its_own_token_outward_and_keeps_its_signature(tmp_path, monkeypatch):
    """Finding: an AI maker always refused its own outward Contagion Tokens, so its own kit could not spread."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    prompts = []

    def automatic_default(_engine, owner, key, name, options, **kwargs):
        prompts.append(kwargs.get("preferred"))
        return list(kwargs.get("preferred") or [])[:1]

    monkeypatch.setattr(rider_choices, "pick", automatic_default)
    assert disease.add_tokens(engine, engine.state.actors[OWNER], engine.state.actors[OUTSIDE], 1, SOURCE,
                              origin=engine.state.actors[OWNER]) is True
    assert disease.tokens(engine, engine.state.actors[OWNER], engine.state.actors[OUTSIDE]) == 1
    assert prompts and prompts[0] and prompts[0][0] == "allow"


def test_vetoed_token_is_reported_as_not_gained(tmp_path, monkeypatch):
    """Finding: a token the Ward refused was still logged as gained.

    add_tokens must say it placed nothing, and the subject must carry no token and no gain line."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    holder, subject = engine.state.actors[SELECTED], engine.state.actors[OUTSIDE]
    monkeypatch.setattr(rider_choices, "pick", lambda *_a, **_k: ["contain"])
    assert disease.add_tokens(engine, holder, subject, 1, SOURCE, origin=holder) is False
    assert disease.tokens(engine, holder, subject) == 0
    gained = [event for event in engine.events
              if "gains a Contagion Token" in str(event.payload) and subject.display_name in str(event.payload)]
    assert gained == []


def test_overlapping_ward_prompt_names_the_ward_maker(tmp_path, monkeypatch):
    """Finding: the spread question did not say which Ward it came from, so overlapping Wards asked identical words."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    asked = []

    def record(_engine, owner, key, name, options, **kwargs):
        asked.append((owner.entity_id, kwargs.get("prompt", "")))
        return ["contain"]

    monkeypatch.setattr(rider_choices, "pick", record)
    disease.add_tokens(engine, engine.state.actors[SELECTED], engine.state.actors[OUTSIDE], 1, SOURCE,
                       origin=engine.state.actors[SELECTED])
    assert asked and asked[0][0] == OWNER
    prompt = asked[0][1]
    assert "Quarantine Ward raised by " + engine.state.actors[OWNER].display_name in prompt


def test_ward_fight_replays_and_verifies(tmp_path):
    """Finding: the ward fight never asserted that its persisted journal verifies and replays."""
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
