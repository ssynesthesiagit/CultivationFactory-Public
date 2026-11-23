"""Silence transmission uses the public zone geometry contract after reload."""
from combat import zones
from combat.ext.smoke_sound_residual import silence_field_path
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle


def test_silence_path_uses_public_containment_for_both_endpoints(tmp_path, monkeypatch):
    _, table, mid = fixture(
        tmp_path, ["TAL_SOUND_FORBIDDEN_SILENCE_FIELD"],
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 0, "y": 6},
                   FOE: {"x": 11, "y": 6}}, seed="F15-PUBLIC-CONTAINMENT")
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
                     and c.destination is not None
                     and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    calls = []
    contains = zones.actor_inside_zone

    def public_contains(live, actor, zone, position=None):
        result = contains(live, actor, zone, position)
        calls.append((actor.entity_id, result))
        return result

    monkeypatch.setattr(zones, "actor_inside_zone", public_contains)
    actors = engine.state.actors
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False
    assert calls == [(OWNER, True), (FOE, False)]
    calls.clear()
    assert silence_field_path(engine, actors[FOE], actors[OWNER], "test:sound") is False
    assert calls == [(FOE, False), (OWNER, True)]
    calls.clear()
    assert silence_field_path(engine, actors[ALLY], actors[FOE], "test:sound") is False
    assert calls == [(ALLY, False), (FOE, False)]


def test_silence_field_is_identified_by_its_record_not_its_printed_name(tmp_path):
    """The area is its record id; a renamed display name must not switch the rule off.

    The Field's name lives in editable typed data. If the gate matched the printed
    name, an owner edit or a re-typed area would silently stop sound crossing the
    Field, which is the printed rule the area exists for.
    """
    _, table, mid = fixture(
        tmp_path, ["TAL_SOUND_FORBIDDEN_SILENCE_FIELD"],
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 0, "y": 6},
                   FOE: {"x": 11, "y": 6}}, seed="F25-FIELD-IDENTITY")
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
                     and c.destination is not None
                     and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    fields = [zone for zone in engine.state.zones.values()
              if zone.active and "TAL_SOUND_FORBIDDEN_SILENCE_FIELD" in str(zone.source_definition_id)]
    assert fields, "the placed Field is saved with the record that created it"
    actors = engine.state.actors
    # Control: the Field blocks the crossing before any rename, so the check
    # below is about identity rather than an inert area.
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False
    for zone in fields:
        zone.trigger_profile["name"] = "Renamed Area"
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False


def test_silence_path_answers_none_for_a_creature_with_no_position(tmp_path):
    """F4 (A2R04-F27): a positionless speaker or listener is a pure query's
    unknown, not a crash. `ray()` needs real positions; the sibling checks in
    `echoes_search_mode` and `mirror_trail_direction` already answer None."""
    _, table, mid = fixture(
        tmp_path, ["TAL_SOUND_FORBIDDEN_SILENCE_FIELD"],
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 0, "y": 6},
                   FOE: {"x": 11, "y": 6}}, seed="F27-NO-POSITION")
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
                     and c.destination is not None
                     and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    actors = engine.state.actors
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False
    # A creature with no square. The model's own field is a square, so the
    # query is asked about a copy that has lost it: the pure path query must
    # answer before any containment or geometry query asks for that square.
    ally = actors[ALLY].model_copy(update={"position": None})
    assert silence_field_path(engine, ally, actors[FOE], "test:sound") is None
    assert silence_field_path(engine, actors[FOE], ally, "test:sound") is None
